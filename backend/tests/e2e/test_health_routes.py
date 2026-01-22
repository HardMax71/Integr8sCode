import pytest
from app.api.routes.health import LivenessResponse, ReadinessResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]


class TestHealthRoutes:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_liveness_probe(self, client: AsyncClient) -> None:
        """GET /health/live returns 200 with status ok."""
        response = await client.get("/api/v1/health/live")

        assert response.status_code == 200
        result = LivenessResponse.model_validate(response.json())

        assert result.status == "ok"
        assert result.uptime_seconds >= 0
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_readiness_probe(self, client: AsyncClient) -> None:
        """GET /health/ready returns 200 with status ok."""
        response = await client.get("/api/v1/health/ready")

        assert response.status_code == 200
        result = ReadinessResponse.model_validate(response.json())

        assert result.status == "ok"
        assert result.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_liveness_no_auth_required(self, client: AsyncClient) -> None:
        """Liveness probe does not require authentication."""
        # client fixture is unauthenticated
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_readiness_no_auth_required(self, client: AsyncClient) -> None:
        """Readiness probe does not require authentication."""
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_uptime_increases(self, client: AsyncClient) -> None:
        """Uptime should be consistent between calls."""
        response1 = await client.get("/api/v1/health/live")
        result1 = LivenessResponse.model_validate(response1.json())

        response2 = await client.get("/api/v1/health/live")
        result2 = LivenessResponse.model_validate(response2.json())

        # Uptime should be same or slightly higher
        assert result2.uptime_seconds >= result1.uptime_seconds
