import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthAPI:

    @pytest.mark.asyncio
    async def test_simple_health_check(self, client: AsyncClient) -> None:  # Inject client directly
        """Verify the simple health check endpoint."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "unhealthy"]
