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
    ) -> None:  # Accept string ID
        try:
            await self.k8s_service.create_execution_pod(
                execution_id=execution_id_str, script=script, python_version=python_version  # Pass string ID
            )
            await self.execution_repo.update_execution(
                execution_id_str, ExecutionUpdate(status=ExecutionStatus.RUNNING).model_dump(exclude_unset=True)
                # Update using string ID
            )
            logger.info(f"K8s pod creation requested for execution {execution_id_str}, status set to RUNNING.")
        except Exception as e:
            error_message = f"Failed to request K8s pod creation: {str(e)}"
            logger.error(error_message, exc_info=True)
            await self.execution_repo.update_execution(
                execution_id_str,  # Update using string ID
                ExecutionUpdate(
                    status=ExecutionStatus.ERROR, errors=error_message
                ).model_dump(exclude_unset=True),
            )
            raise IntegrationException(status_code=500, detail=error_message) from e

    async def _get_k8s_execution_output(self, execution_id_str: str) -> tuple[  # Accept string ID
        Optional[str], Optional[str], Optional[str], Optional[dict]]:
        try:
            output, phase, resource_usage = await self.k8s_service.get_pod_logs(execution_id_str)  # Pass string ID
            logger.info(
                f"Retrieved K8s results for {execution_id_str}. Phase: {phase}. Resource usage found: {resource_usage is not None}")
            return output, None, phase, resource_usage
        except KubernetesPodError as e:
            logger.error(f"Error retrieving pod results for {execution_id_str}: {str(e)}")
            return None, str(e), ExecutionStatus.ERROR, None
        except ApiException as e:
            error_msg = f"Kubernetes API error for {execution_id_str}: {e.status} {e.reason}"
            logger.error(error_msg)
            return None, error_msg, ExecutionStatus.ERROR, None
        except Exception as e:
            error_msg = f"Unexpected error retrieving K8s results for {execution_id_str}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg, ExecutionStatus.ERROR, None

    async def execute_script(
            self, script: str, python_version: str = "3.11"
    ) -> ExecutionInDB:  # Return the DB object with ObjectId
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

            SCRIPT_EXECUTIONS.labels(
                status="initiated", python_version=python_version
            ).inc()

            await asyncio.sleep(0.1)

            final_execution_state = await self.execution_repo.get_execution(execution_id_str)
            if not final_execution_state:
                logger.error(f"Failed to reload execution record {execution_id_str} after creation.")
                raise IntegrationException(status_code=500, detail="Failed to retrieve execution record after creation")
            return final_execution_state  # Return ExecutionInDB instance (id is ObjectId)

        except Exception as e:
            logger.error(f"Error during script execution request: {str(e)}", exc_info=True)
            SCRIPT_EXECUTIONS.labels(
                status="error", python_version=python_version
            ).inc()
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
                                           detail=f"Internal server error during script execution request: {str(e)}") from e

        finally:
            EXECUTION_DURATION.labels(python_version=python_version).observe(
                time() - start_time
            )
            ACTIVE_EXECUTIONS.dec()

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:  # Return the DB object with ObjectId
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            logger.warning(f"Execution record not found in DB for ID: {execution_id}")
            ERROR_COUNTER.labels(error_type="ExecutionNotFound").inc()
            raise IntegrationException(status_code=404, detail="Execution not found")

        if execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.ERROR]:
            logger.info(f"Returning final state ({execution.status}) for execution {execution_id} from DB.")
            return execution

        logger.info(f"Execution {execution_id} has status {execution.status}, checking K8s for updates.")
        output, error_msg, final_phase, resource_usage = await self._get_k8s_execution_output(execution_id)

        update_data: Dict[str, Any] = {}
        final_status = execution.status

        if final_phase:
            if final_phase == "Succeeded":
                final_status = ExecutionStatus.COMPLETED
                SCRIPT_EXECUTIONS.labels(status="success", python_version=execution.python_version).inc()
                logger.info(f"Execution {execution_id} completed successfully based on K8s pod phase.")
            else:
                final_status = ExecutionStatus.ERROR
                SCRIPT_EXECUTIONS.labels(status="error", python_version=execution.python_version).inc()
                ERROR_COUNTER.labels(error_type="KubernetesPodFailed").inc()
                logger.warning(
                    f"Execution {execution_id} failed or errored based on K8s pod phase: {final_phase}. Error msg: {error_msg}")

            update_data["status"] = final_status
            update_data["output"] = output if output is not None else execution.output
            update_data["errors"] = error_msg if error_msg else execution.errors

            if resource_usage:
                update_data["resource_usage"] = resource_usage
                if resource_usage.get("exit_code", 0) != 0:
                    final_status = ExecutionStatus.ERROR
                    update_data["status"] = final_status
                    if not update_data.get("errors"):
                        update_data["errors"] = f"Script exited with code {resource_usage['exit_code']}"
            elif final_status == ExecutionStatus.ERROR and not update_data.get("errors"):
                update_data["errors"] = f"Pod phase was {final_phase} but failed to retrieve detailed logs or metrics."

        if final_phase:
            logger.info(f"Updating execution {execution_id} in DB with final status: {final_status}")
            update_payload = ExecutionUpdate(**update_data).model_dump(exclude_unset=True)
            await self.execution_repo.update_execution(execution_id, update_payload)
            updated_execution = await self.execution_repo.get_execution(execution_id)
            if not updated_execution:
                logger.error(f"Failed to reload execution record {execution_id} after final update.")
                execution.status = final_status
                execution.output = update_data.get("output", execution.output)
                execution.errors = update_data.get("errors", execution.errors)
                execution.resource_usage = update_data.get("resource_usage", execution.resource_usage)
                return execution
            return updated_execution
        else:
            logger.info(
                f"No final K8s status found for execution {execution_id}, returning current DB status: {execution.status}")
            return execution


def get_execution_service(
        execution_repo: ExecutionRepository = Depends(get_execution_repository),
        k8s_service: KubernetesService = Depends(get_kubernetes_service),
) -> ExecutionService:
    return ExecutionService(execution_repo, k8s_service)
