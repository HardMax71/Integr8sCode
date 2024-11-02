import pytest
from app.services.kubernetes_service import KubernetesService
from kubernetes.client.rest import ApiException


class TestKubernetesService:
    @pytest.fixture(autouse=True)
    async def setup(self):
        self.k8s_service = KubernetesService()

    @pytest.mark.asyncio
    async def test_create_execution_pod(self):
        execution_id = "test-123"
        script = "print('Hello, World!')"
        python_version = "3.11"

        try:
            await self.k8s_service.create_execution_pod(
                execution_id=execution_id, script=script, python_version=python_version
            )

            # Verify pod creation
            pod = await self.k8s_service.v1.read_namespaced_pod(
                name=f"execution-{execution_id}", namespace="default"
            )
            assert pod.metadata.name == f"execution-{execution_id}"

        except ApiException as e:
            pytest.fail(f"Failed to create pod: {str(e)}")
        finally:
            # Cleanup
            try:
                await self.k8s_service.v1.delete_namespaced_pod(
                    name=f"execution-{execution_id}", namespace="default"
                )
            except ApiException:
                pass

    @pytest.mark.asyncio
    async def test_get_pod_logs(self):
        execution_id = "test-456"
        script = "print('Test log output')"

        try:
            await self.k8s_service.create_execution_pod(
                execution_id=execution_id, script=script, python_version="3.11"
            )

            logs = await self.k8s_service.get_pod_logs(execution_id)
            assert "Test log output" in logs

        except ApiException as e:
            pytest.fail(f"Failed to get pod logs: {str(e)}")
