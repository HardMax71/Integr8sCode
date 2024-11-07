from app.core.execution import ExecutionEngine
from app.services.kubernetes_service import KubernetesService
from typing import Optional


class K8sExecutionEngine(ExecutionEngine):
    def __init__(self, k8s_service: KubernetesService):
        self.k8s_service = k8s_service

    async def start_execution(
        self, execution_id: str, script: str, runtime_version: str
    ) -> None:
        await self.k8s_service.create_execution_pod(
            execution_id=execution_id, script=script, python_version=runtime_version
        )

    async def get_execution_output(
        self, execution_id: str
    ) -> tuple[str, Optional[str]]:
        try:
            logs = await self.k8s_service.get_pod_logs(execution_id)
            return logs, None
        except Exception as e:
            return "", str(e)
