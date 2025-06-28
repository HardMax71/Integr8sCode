import asyncio
from enum import Enum
from time import time
from typing import Any, Dict, Optional

from app.config import get_settings
from app.core.exceptions import IntegrationException
from app.core.logging import logger
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
from app.schemas.execution import ExecutionCreate, ExecutionInDB, ExecutionUpdate
from app.services.kubernetes_service import (
    KubernetesPodError,
    KubernetesService,
    get_kubernetes_service,
)
from fastapi import Depends
from kubernetes.client.rest import ApiException


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class ExecutionService:
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
            self, execution_id_str: str, script: str, python_version: str
    ) -> None:
        try:
            # Python-specific configuration
            image = f"python:{python_version}-slim"
            command = ["python", "/scripts/script.py"]
            config_map_data = {
                "script.py": script
            }

            await self.k8s_service.create_execution_pod(
                execution_id=execution_id_str,
                image=image,
                command=command,
                config_map_data=config_map_data
            )

            await self.execution_repo.update_execution(
                execution_id_str,
                ExecutionUpdate(status=ExecutionStatus.RUNNING).model_dump(exclude_unset=True)
            )
            logger.info(f"K8s pod creation requested for execution {execution_id_str}, status set to RUNNING.")
        except Exception as e:
            error_message = f"Failed to request K8s pod creation: {str(e)}"
            logger.error(error_message, exc_info=True)
            await self.execution_repo.update_execution(
                execution_id_str,
                ExecutionUpdate(
                    status=ExecutionStatus.ERROR, errors=error_message
                ).model_dump(exclude_unset=True),
            )
            raise IntegrationException(status_code=500, detail=error_message) from e

    async def _get_k8s_execution_output(
            self,
            execution_id_str: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[dict]]:
        output: Optional[str] = None
        error_msg: Optional[str] = None
        # assume error unless the try succeeds
        phase: Optional[str] = ExecutionStatus.ERROR
        resource_usage: Optional[dict] = None

        try:
            output, phase, resource_usage = await self.k8s_service.get_pod_logs(execution_id_str)
            logger.info(
                f"Retrieved K8s results for {execution_id_str}. "
                f"Phase: {phase}. Resource usage found: {resource_usage is not None}"
            )
        except KubernetesPodError as e:
            error_msg = str(e)
            logger.error(f"Error retrieving pod results for {execution_id_str}: {error_msg}")
        except ApiException as e:
            error_msg = f"Kubernetes API error for {execution_id_str}: {e.status} {e.reason}"
            logger.error(error_msg, exc_info=True)
        except Exception as e:
            error_msg = f"Unexpected error retrieving K8s results for {execution_id_str}: {e}"
            logger.error(error_msg, exc_info=True)

        return output, error_msg, phase, resource_usage

    async def _try_finalize_execution(self, execution: ExecutionInDB) -> Optional[ExecutionInDB]:
        """
        Checks K8s for a final status. If found, updates the database and
        returns the updated execution object. Otherwise, returns None.
        """
        output, _, final_phase, resources = await self._get_k8s_execution_output(execution.id)

        update_data = {}

        # Now we only have basic metrics from K8s
        if resources:
            exit_code = resources.get("exit_code", 1)

            if exit_code == 0:
                update_data = {
                    "status": ExecutionStatus.COMPLETED,
                    "output": output or "",
                    "errors": None,
                    "resource_usage": resources  # Only has exit_code, execution_time, pod_phase
                }
            else:
                # Script failed - output contains stderr/stdout
                error_details = output or f"Script failed with exit code {exit_code}"
                update_data = {
                    "status": ExecutionStatus.ERROR,
                    "output": "",
                    "errors": error_details,
                    "resource_usage": resources
                }
        else:
            # No metrics at all - use pod phase
            if final_phase == "Succeeded":
                update_data = {
                    "status": ExecutionStatus.COMPLETED,
                    "output": output or "",
                    "errors": None,
                    "resource_usage": {"pod_phase": final_phase}
                }
            else:
                error_details = output or f"Pod failed with phase '{final_phase}'"
                update_data = {
                    "status": ExecutionStatus.ERROR,
                    "output": "",
                    "errors": error_details,
                    "resource_usage": {"pod_phase": final_phase}
                }

        if not update_data:
            return None

        logger.info(f"Finalizing execution {execution.id} with status: {update_data['status']}")
        update_payload = ExecutionUpdate(**update_data).model_dump(exclude_unset=True)
        await self.execution_repo.update_execution(execution.id, update_payload)

        updated_execution = await self.execution_repo.get_execution(execution.id)
        if not updated_execution:
            logger.error(f"FATAL: Failed to reload execution record {execution.id} after final update.")
            raise IntegrationException(status_code=500, detail="Failed to retrieve execution after update.")

        status_label = "success" if updated_execution.status == ExecutionStatus.COMPLETED else "error"
        SCRIPT_EXECUTIONS.labels(status=status_label, python_version=updated_execution.python_version).inc()
        if status_label == "error":
            ERROR_COUNTER.labels(error_type="ScriptExecutionError").inc()

        return updated_execution

    async def execute_script(
            self, script: str, python_version: str = "3.11"
    ) -> ExecutionInDB:
        ACTIVE_EXECUTIONS.inc()
        start_time = time()
        inserted_oid = None

        try:
            if python_version not in self.settings.SUPPORTED_PYTHON_VERSIONS:
                raise IntegrationException(status_code=400, detail=f"Unsupported Python version: {python_version}")

            execution_create = ExecutionCreate(
                script=script,
                python_version=python_version,
                status=ExecutionStatus.QUEUED,
            )
            execution_to_insert = ExecutionInDB(**execution_create.model_dump())
            inserted_oid = await self.execution_repo.create_execution(execution_to_insert)
            execution_id_str = str(inserted_oid)
            logger.info(f"Created execution record {execution_id_str} with status QUEUED.")

            await self._start_k8s_execution(
                execution_id_str, script, python_version
            )
            SCRIPT_EXECUTIONS.labels(status="initiated", python_version=python_version).inc()
            await asyncio.sleep(0.1)

            final_execution_state = await self.execution_repo.get_execution(execution_id_str)
            if not final_execution_state:
                raise IntegrationException(status_code=500, detail="Failed to retrieve execution record after creation")
            return final_execution_state

        except Exception as e:
            logger.error(f"Error during script execution request: {str(e)}", exc_info=True)
            ERROR_COUNTER.labels(error_type=type(e).__name__).inc()
            if inserted_oid:
                await self.execution_repo.update_execution(
                    str(inserted_oid),
                    ExecutionUpdate(status=ExecutionStatus.ERROR, errors=str(e)).model_dump(exclude_unset=True)
                )
            if isinstance(e, IntegrationException):
                raise
            else:
                raise IntegrationException(status_code=500,
                                           detail=f"Internal server error during script execution request: "
                                                  f"{str(e)}") from e
        finally:
            EXECUTION_DURATION.labels(python_version=python_version).observe(time() - start_time)
            ACTIVE_EXECUTIONS.dec()

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            raise IntegrationException(status_code=404, detail="Execution not found")

        if execution.status in [ExecutionStatus.QUEUED, ExecutionStatus.RUNNING]:
            logger.info(f"Execution {execution_id} is in-progress. Checking K8s for final status...")
            finalized_execution = await self._try_finalize_execution(execution)
            return finalized_execution or execution

        logger.info(f"Returning final state ({execution.status}) for execution {execution_id} from DB.")
        return execution


def get_execution_service(
        execution_repo: ExecutionRepository = Depends(get_execution_repository),
        k8s_service: KubernetesService = Depends(get_kubernetes_service),
) -> ExecutionService:
    return ExecutionService(execution_repo, k8s_service)
