import pytest
from app.services.execution_service import ExecutionService
from app.services.kubernetes_service import KubernetesService
from app.db.repositories.execution_repository import ExecutionRepository


class TestExecutionService:
    @pytest.fixture(autouse=True)
    async def setup(self, db):
        self.k8s_service = KubernetesService()
        self.execution_repo = ExecutionRepository(db)
        self.execution_service = ExecutionService(
            execution_repo=self.execution_repo, k8s_service=self.k8s_service
        )

    @pytest.mark.asyncio
    async def test_execute_script(self):
        script = "print('Test execution')"
        result = await self.execution_service.execute_script(script)

        assert result.script == script
        assert result.status in ["queued", "running"]

        # Wait for execution to complete
        final_result = await self.execution_service.get_execution_result(result.id)
        assert final_result.status == "completed"
        assert "Test execution" in final_result.output

    @pytest.mark.asyncio
    async def test_get_k8s_resource_limits(self):
        limits = await self.execution_service.get_k8s_resource_limits()

        assert "cpu_limit" in limits
        assert "memory_limit" in limits
        assert "cpu_request" in limits
        assert "memory_request" in limits
        assert "execution_timeout" in limits
        assert "supported_python_versions" in limits
