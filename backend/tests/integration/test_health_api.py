import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthAPI:

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient) -> None:  # Inject client directly
        """Verify the health check endpoint."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
