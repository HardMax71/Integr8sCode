import logging
from contextlib import contextmanager
from time import time

from app.config import get_settings
from app.core.exceptions import IntegrationException
from app.core.metrics import (
    SCRIPT_EXECUTIONS,
    EXECUTION_DURATION,
    ACTIVE_EXECUTIONS,
    ERROR_COUNTER
)
from app.db.repositories.execution_repository import (
    ExecutionRepository,
    get_execution_repository,
)
from app.models.execution import ExecutionCreate, ExecutionInDB, ExecutionUpdate
from app.services.kubernetes_service import KubernetesService, get_kubernetes_service
from fastapi import Depends
from kubernetes.client.rest import ApiException


class ExecutionService:
    def __init__(
            self, execution_repo: ExecutionRepository, k8s_service: KubernetesService
    ):
        self.execution_repo = execution_repo
        self.k8s_service = k8s_service
        self.settings = get_settings()

    async def get_k8s_resource_limits(self):
        return {
            "cpu_limit": self.settings.K8S_POD_CPU_LIMIT,
            "memory_limit": self.settings.K8S_POD_MEMORY_LIMIT,
            "cpu_request": self.settings.K8S_POD_CPU_REQUEST,
            "memory_request": self.settings.K8S_POD_MEMORY_REQUEST,
            "execution_timeout": self.settings.K8S_POD_EXECUTION_TIMEOUT,
            "supported_python_versions": self.settings.SUPPORTED_PYTHON_VERSIONS,
        }

    async def execute_script(
            self, script: str, python_version: str = "3.11"
    ) -> ExecutionInDB:
        ACTIVE_EXECUTIONS.inc()
        start_time = time()

        try:
            execution = ExecutionCreate(script=script, python_version=python_version)
            execution_in_db = ExecutionInDB(**execution.dict())
            await self.execution_repo.create_execution(execution_in_db)

            try:
                await self.k8s_service.create_execution_pod(
                    execution_in_db.id, script, python_version
                )
                SCRIPT_EXECUTIONS.labels(
                    status="success",
                    python_version=python_version
                ).inc()

            except Exception as e:
                error_message = f"Failed to create execution pod: {str(e)}"
                logging.error(error_message)
                await self.execution_repo.update_execution(
                    execution_in_db.id,
                    ExecutionUpdate(status="failed", errors=error_message).dict(),
                )

                SCRIPT_EXECUTIONS.labels(
                    status="error",
                    python_version=python_version
                ).inc()
                ERROR_COUNTER.labels(
                    error_type=type(e).__name__
                ).inc()

                raise IntegrationException(status_code=500, detail=error_message)

            return await self.execution_repo.get_execution(execution_in_db.id)

        finally:
            EXECUTION_DURATION.labels(
                python_version=python_version
            ).observe(time() - start_time)
            ACTIVE_EXECUTIONS.dec()

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            ERROR_COUNTER.labels(error_type="ExecutionNotFound").inc()
            raise IntegrationException(status_code=404, detail="Execution not found")

        if execution.status in ["completed", "failed"]:
            return execution

        try:
            logs = await self.k8s_service.get_pod_logs(execution_id)
            update_data = ExecutionUpdate(status="completed", output=logs).dict()
            await self.execution_repo.update_execution(execution_id, update_data)

            SCRIPT_EXECUTIONS.labels(
                status="success",
                python_version=execution.python_version
            ).inc()

        except ApiException as e:
            if e.status == 400 and "ContainerCreating" in e.body:
                logging.info(f"Pod {execution_id} is not ready yet.")
                return execution
            else:
                update_data = ExecutionUpdate(status="failed", errors=str(e)).dict()
                await self.execution_repo.update_execution(execution_id, update_data)

                SCRIPT_EXECUTIONS.labels(
                    status="error",
                    python_version=execution.python_version
                ).inc()
                ERROR_COUNTER.labels(
                    error_type="KubernetesApiError"
                ).inc()

        except Exception as e:
            update_data = ExecutionUpdate(status="failed", errors=str(e)).dict()
            await self.execution_repo.update_execution(execution_id, update_data)

            SCRIPT_EXECUTIONS.labels(
                status="error",
                python_version=execution.python_version
            ).inc()
            ERROR_COUNTER.labels(
                error_type=type(e).__name__
            ).inc()

        return await self.execution_repo.get_execution(execution_id)


def get_execution_service(
        execution_repo: ExecutionRepository = Depends(get_execution_repository),
        k8s_service: KubernetesService = Depends(get_kubernetes_service),
) -> ExecutionService:
    return ExecutionService(execution_repo, k8s_service)