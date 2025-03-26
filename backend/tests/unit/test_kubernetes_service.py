import asyncio

import pytest
from app.services.kubernetes_service import KubernetesService, KubernetesServiceManager
from kubernetes.client.rest import ApiException


class TestKubernetesService:
    @pytest.fixture(autouse=True)
    async def setup(self) -> None:
        self.manager = KubernetesServiceManager()
        self.k8s_service = KubernetesService(manager=self.manager)

    @pytest.mark.asyncio
    async def test_create_execution_pod(self) -> None:
        execution_id = "test-123"
        script = "print('Hello, World!')"
        python_version = "3.11"

        try:
            await self.k8s_service.create_execution_pod(
                execution_id=execution_id, script=script, python_version=python_version
            )

            # Verify pod creation - note: v1 methods are not directly awaitable
            pod = await asyncio.to_thread(
                self.k8s_service.v1.read_namespaced_pod,
                name=f"execution-{execution_id}",
                namespace="default"
            )
            assert pod.metadata.name == f"execution-{execution_id}"

        except ApiException as e:
            pytest.fail(f"Failed to create pod: {str(e)}")
        finally:
            # Cleanup - note: v1 methods are not directly awaitable
            try:
                await asyncio.to_thread(
                    self.k8s_service.v1.delete_namespaced_pod,
                    name=f"execution-{execution_id}",
                    namespace="default"
                )
            except ApiException:
                pass

    @pytest.mark.asyncio
    async def test_get_pod_logs(self) -> None:
        execution_id = "test-456"
        script = "print('Test log output')"

        try:
            await self.k8s_service.create_execution_pod(
                execution_id=execution_id, script=script, python_version="3.11"
            )

            # get_pod_logs returns a tuple (script_output, pod_phase, resource_usage)
            output, phase, resource_usage = await self.k8s_service.get_pod_logs(execution_id)
            assert "Test log output" in output

        except ApiException as e:
            pytest.fail(f"Failed to get pod logs: {str(e)}")
