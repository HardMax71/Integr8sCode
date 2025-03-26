from enum import Enum
from time import time
from typing import Any, Dict, Optional

from fastapi import Depends
from kubernetes.client.rest import ApiException

from app.config import get_settings
from app.core.exceptions import IntegrationException
from app.core.metrics import (
    ACTIVE_EXECUTIONS,
    ERROR_COUNTER,
    EXECUTION_DURATION,
    SCRIPT_EXECUTIONS,
)
from app.db.repositories.execution_repository import (
    ExecutionRepository,
    get_execution_repository,
)
from app.models.execution import ExecutionCreate, ExecutionInDB, ExecutionUpdate
from app.services.kubernetes_service import KubernetesService, get_kubernetes_service


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionService:
    """
    Service for managing script executions.
    Handles business logic, execution flow, and Kubernetes integration.
    """

    def __init__(
            self, execution_repo: ExecutionRepository, k8s_service: KubernetesService
    ):
        self.execution_repo = execution_repo
        self.k8s_service = k8s_service
        self.settings = get_settings()

    async def get_k8s_resource_limits(self) -> Dict[str, Any]:
        return {
            "cpu_limit": self.settings.K8S_POD_CPU_LIMIT,
            "memory_limit": self.settings.K8S_POD_MEMORY_LIMIT,
            "cpu_request": self.settings.K8S_POD_CPU_REQUEST,
            "memory_request": self.settings.K8S_POD_MEMORY_REQUEST,
            "execution_timeout": self.settings.K8S_POD_EXECUTION_TIMEOUT,
            "supported_python_versions": self.settings.SUPPORTED_PYTHON_VERSIONS,
        }

    async def _start_k8s_execution(
            self, execution_id: str, script: str, python_version: str
    ) -> None:
        try:
            await self.k8s_service.create_execution_pod(
                execution_id=execution_id, script=script, python_version=python_version
            )
            await self.execution_repo.update_execution(
                execution_id, ExecutionUpdate(status=ExecutionStatus.RUNNING).dict()
            )
        except Exception as e:
            error_message = f"Failed to start K8s execution: {str(e)}"
            await self.execution_repo.update_execution(
                execution_id,
                ExecutionUpdate(
                    status=ExecutionStatus.FAILED, errors=error_message
                ).dict(),
            )
            raise IntegrationException(status_code=500, detail=error_message) from e

    async def _get_k8s_execution_output(self, execution_id: str) -> tuple[
        Optional[str], Optional[str], Optional[str], Optional[dict]]:
        """
        Returns a tuple: (output, error, phase, resource_usage).
        It calls the Kubernetes service to retrieve the pod’s logs, final phase, and resource usage.
        """
        try:
            output, phase, resource_usage = await self.k8s_service.get_pod_logs(execution_id)
            return output, None, phase, resource_usage
        except ApiException as e:
            if e.status == 400 and "ContainerCreating" in e.body:
                return None, None, None, None
            return None, str(e), None, None
        except Exception as e:
            return None, str(e), None, None

    async def execute_script(
            self, script: str, python_version: str = "3.11"
    ) -> ExecutionInDB:
        ACTIVE_EXECUTIONS.inc()
        start_time = time()

        try:
            # Create initial execution record
            execution = ExecutionCreate(
                script=script,
                python_version=python_version,
                status=ExecutionStatus.QUEUED,
            )
            execution_in_db = ExecutionInDB(**execution.dict())
            await self.execution_repo.create_execution(execution_in_db)

            try:
                # Start execution in Kubernetes
                await self._start_k8s_execution(
                    execution_in_db.id, script, python_version
                )
                SCRIPT_EXECUTIONS.labels(
                    status="success", python_version=python_version
                ).inc()

                exec_result: Optional[ExecutionInDB] = await self.execution_repo.get_execution(execution_in_db.id)
                if not exec_result:
                    raise ValueError("Execution result is none")
            except Exception as e:
                SCRIPT_EXECUTIONS.labels(
                    status="error", python_version=python_version
                ).inc()
                ERROR_COUNTER.labels(error_type=type(e).__name__).inc()
                raise

            return exec_result
        finally:
            EXECUTION_DURATION.labels(python_version=python_version).observe(
                time() - start_time
            )
            ACTIVE_EXECUTIONS.dec()

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            ERROR_COUNTER.labels(error_type="ExecutionNotFound").inc()
            raise IntegrationException(status_code=404, detail="Execution not found")

        # If already completed or failed (i.e. result has been finalized),
        # return the stored execution record from the DB.
        if execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]:
            return execution

        # Otherwise, try to get fresh data (logs, phase, resource_usage)
        output, error, phase, resource_usage = await self._get_k8s_execution_output(execution_id)
        # If nothing is returned, assume execution is still in progress.
        if output is None and error is None and phase is None:
            return execution

        # Build update data with resource usage and update the record.
        exit_code = resource_usage.get("exit_code", 0) if resource_usage else 0
        if error or exit_code != 0:
            update_data = ExecutionUpdate(
                status=ExecutionStatus.FAILED,
                errors=error or "Script exited with non-zero exit code",
                output=output,
                resource_usage=resource_usage,
            ).dict()
            SCRIPT_EXECUTIONS.labels(status="error", python_version=execution.python_version).inc()
            ERROR_COUNTER.labels(error_type="ExecutionError").inc()
        else:
            update_data = ExecutionUpdate(
                status=ExecutionStatus.COMPLETED,
                output=output,
                resource_usage=resource_usage,
            ).dict()
            SCRIPT_EXECUTIONS.labels(status="success", python_version=execution.python_version).inc()

        await self.execution_repo.update_execution(execution_id, update_data)
        updated_execution = await self.execution_repo.get_execution(execution_id)
        if not updated_execution:
            raise IntegrationException(status_code=404, detail="Updated execution not found")
        return updated_execution


def get_execution_service(
        execution_repo: ExecutionRepository = Depends(get_execution_repository),
        k8s_service: KubernetesService = Depends(get_kubernetes_service),
) -> ExecutionService:
    return ExecutionService(execution_repo, k8s_service)
