from app.config import get_settings
from app.db.repositories.execution_repository import ExecutionRepository
from app.db.repositories.execution_repository import get_execution_repository
from app.models.execution import ExecutionInDB
from app.services.execution_orchestrator import ExecutionOrchestrator
from app.services.k8s_engine import K8sExecutionEngine
from app.services.kubernetes_service import KubernetesService
from app.services.kubernetes_service import get_kubernetes_service
from fastapi import Depends


class ExecutionService:
    def __init__(self, orchestrator: ExecutionOrchestrator, settings=get_settings()):
        self.orchestrator = orchestrator
        self.settings = settings

    async def execute_script(
        self, script: str, python_version: str = "3.11"
    ) -> ExecutionInDB:
        return await self.orchestrator.start_execution(script, python_version)

    async def get_execution_result(self, execution_id: str) -> ExecutionInDB:
        return await self.orchestrator.get_execution_result(execution_id)

    async def get_k8s_resource_limits(self):
        return {
            "cpu_limit": self.settings.K8S_POD_CPU_LIMIT,
            "memory_limit": self.settings.K8S_POD_MEMORY_LIMIT,
            "cpu_request": self.settings.K8S_POD_CPU_REQUEST,
            "memory_request": self.settings.K8S_POD_MEMORY_REQUEST,
            "execution_timeout": self.settings.K8S_POD_EXECUTION_TIMEOUT,
            "supported_python_versions": self.settings.SUPPORTED_PYTHON_VERSIONS,
        }


def get_execution_service(
    execution_repo: ExecutionRepository = Depends(get_execution_repository),
    k8s_service: KubernetesService = Depends(get_kubernetes_service),
) -> ExecutionService:
    engine = K8sExecutionEngine(k8s_service)
    orchestrator = ExecutionOrchestrator(execution_repo, engine)
    return ExecutionService(orchestrator)
