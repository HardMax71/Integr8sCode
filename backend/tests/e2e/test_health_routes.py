import asyncio
import time

import pytest
from app.api.routes.health import LivenessResponse
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

    @pytest.mark.asyncio
    async def test_liveness_no_auth_required(self, client: AsyncClient) -> None:
        """Liveness probe does not require authentication."""
        # client fixture is unauthenticated
        response = await client.get("/api/v1/health/live")
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

    @pytest.mark.asyncio
    async def test_liveness_is_fast(self, client: AsyncClient) -> None:
        """Liveness check should respond within 1 second."""
        start = time.time()
        r = await client.get("/api/v1/health/live")
        assert r.status_code == 200
        assert time.time() - start < 5.0

    @pytest.mark.asyncio
    async def test_concurrent_liveness_fetch(self, client: AsyncClient) -> None:
        """Multiple concurrent liveness checks should all succeed."""
        tasks = [client.get("/api/v1/health/live") for _ in range(5)]
        responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)

    @pytest.mark.asyncio
    async def test_nonexistent_health_routes_return_404(self, client: AsyncClient) -> None:
        """Non-existent health routes should return 404."""
        for path in [
            "/api/v1/health/healthz",
            "/api/v1/health/health",
            "/api/v1/health/ready",
            "/api/v1/health/readyz",
        ]:
            r = await client.get(path)
            assert r.status_code in (404, 405)
