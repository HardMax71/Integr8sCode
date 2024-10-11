import logging

from app.config import get_settings
from app.core.exceptions import IntegrationException
from app.db.repositories.execution_repository import ExecutionRepository, get_execution_repository
from app.models.execution import ExecutionCreate, ExecutionInDB, ExecutionUpdate
from app.services.kubernetes_service import KubernetesService, get_kubernetes_service
from fastapi import Depends
from kubernetes.client.rest import ApiException


class ExecutionService:
    def __init__(self, execution_repo: ExecutionRepository, k8s_service: KubernetesService):
        self.execution_repo = execution_repo
        self.k8s_service = k8s_service
        self.settings = get_settings()

    async def get_k8s_resource_limits(self):
        return {
            "cpu_limit": self.settings.K8S_POD_CPU_LIMIT,
            "memory_limit": self.settings.K8S_POD_MEMORY_LIMIT,
            "cpu_request": self.settings.K8S_POD_CPU_REQUEST,
            "memory_request": self.settings.K8S_POD_MEMORY_REQUEST
        }

    async def execute_script(self, script: str) -> ExecutionInDB:
        execution = ExecutionCreate(script=script)
        execution_in_db = ExecutionInDB(**execution.dict())
        await self.execution_repo.create_execution(execution_in_db)

        try:
            await self.k8s_service.create_execution_pod(execution_in_db.id, script)
        except Exception as e:
            error_message = f"Failed to create execution pod: {str(e)}"
            logging.error(error_message)
            await self.execution_repo.update_execution(
                execution_in_db.id,
                ExecutionUpdate(status="failed", errors=error_message).dict()
            )
            raise IntegrationException(status_code=500, detail=error_message)

        return await self.execution_repo.get_execution(execution_in_db.id)

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        execution = await self.execution_repo.get_execution(execution_id)
        if not execution:
            raise IntegrationException(status_code=404, detail="Execution not found")

        if execution.status in ["completed", "failed"]:
            return execution

        try:
            logs = await self.k8s_service.get_pod_logs(execution_id)
            update_data = ExecutionUpdate(status="completed", output=logs).dict()
            await self.execution_repo.update_execution(execution_id, update_data)
        except ApiException as e:
            # Handle specific Kubernetes API exceptions
            if e.status == 400 and "ContainerCreating" in e.body:
                # Pod is still starting; return current execution status
                logging.info(f"Pod {execution_id} is not ready yet.")
                return execution
            else:
                # Mark execution as failed
                update_data = ExecutionUpdate(status="failed", errors=str(e)).dict()
                await self.execution_repo.update_execution(execution_id, update_data)
        except Exception as e:
            # General exception handling
            update_data = ExecutionUpdate(status="failed", errors=str(e)).dict()
            await self.execution_repo.update_execution(execution_id, update_data)

        return await self.execution_repo.get_execution(execution_id)


def get_execution_service(
        execution_repo: ExecutionRepository = Depends(get_execution_repository),
        k8s_service: KubernetesService = Depends(get_kubernetes_service)
) -> ExecutionService:
    return ExecutionService(execution_repo, k8s_service)
