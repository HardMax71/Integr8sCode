from typing import Dict, Any, Tuple

from app.core.logging import logger
from app.services.kubernetes_service import KubernetesServiceManager


class MockPodStatus:
    def __init__(self, phase: str = "Running"):
        self.phase = phase


class MockPod:
    def __init__(self, phase: str = "Running"):
        self.status = MockPodStatus(phase)


class MockV1Api:
    def read_namespaced_pod(self, name: str, namespace: str) -> MockPod:
        return MockPod()


class MockKubernetesService:
    NAMESPACE = "default"

    def __init__(self, manager: KubernetesServiceManager):
        self.manager = manager
        self.settings = None
        self._is_healthy = True
        self._active_pods: Dict[str, Any] = {}
        self.v1 = MockV1Api()

    async def create_execution_pod(
            self,
            execution_id: str,
            image: str,
            command: list,
            config_map_data: dict
    ) -> None:
        logger.info(f"Mock: Creating pod for execution {execution_id} with image {image}")
        self._active_pods[execution_id] = {
            'image': image,
            'command': command,
            'config_map_data': config_map_data
        }

    async def get_pod_logs(self, execution_id: str) -> Tuple[Dict[str, Any], str]:
        logger.info(f"Mock: Getting logs for execution {execution_id}")

        metrics = {
            'stdout': f'Mock output for execution {execution_id}',
            'stderr': '',
            'exit_code': 0,
            'resource_usage': {
                'execution_time_wall_seconds': 1.5,
                'cpu_time_jiffies': 150,
                'clk_tck_hertz': 100,
                'peak_memory_kb': 1024
            }
        }
        final_phase = 'Succeeded'

        return metrics, final_phase

    def check_health(self) -> bool:
        return self._is_healthy

    async def graceful_shutdown(self) -> None:
        logger.info("Mock: Kubernetes service shutdown")
        self._active_pods.clear()


def get_mock_kubernetes_service() -> MockKubernetesService:
    manager = KubernetesServiceManager()
    return MockKubernetesService(manager)
