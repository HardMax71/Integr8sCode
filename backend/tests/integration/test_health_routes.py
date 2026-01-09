import asyncio
import time
from typing import Dict

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestHealthRoutes:
    """Backend availability checks (no dedicated health endpoints)."""

    @pytest.mark.asyncio
    async def test_liveness_available(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/health/live")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert data.get("status") == "ok"

    @pytest.mark.asyncio
    async def test_liveness_no_auth_required(self, client: AsyncClient) -> None:
        """Liveness should not require authentication."""
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    @pytest.mark.asyncio
    async def test_readiness_basic(self, client: AsyncClient) -> None:
        """Readiness endpoint exists and responds 200 when ready."""
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    @pytest.mark.asyncio
    async def test_liveness_is_fast(self, client: AsyncClient) -> None:
        start = time.time()
        r = await client.get("/api/v1/health/live")
        assert r.status_code == 200
        assert time.time() - start < 1.0

    @pytest.mark.asyncio
    async def test_concurrent_liveness_fetch(self, client: AsyncClient) -> None:
        tasks = [client.get("/api/v1/health/live") for _ in range(5)]
        responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)

    @pytest.mark.asyncio
    async def test_app_responds_during_load(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        # Create some load with execution requests
        async def create_load() -> int | None:
            execution_request = {
                "script": "print('Load test')",
                "lang": "python",
                "lang_version": "3.11"
            }
            try:
                response = await client.post("/api/v1/execute", json=execution_request)
                return response.status_code
            except Exception:
                return None

        # Start load generation
        load_tasks = [create_load() for _ in range(5)]

        # Check readiness during load
        r0 = await client.get("/api/v1/health/live")
        assert r0.status_code == 200

        # Wait for load tasks to complete
        await asyncio.gather(*load_tasks, return_exceptions=True)

        # Check readiness after load
        r1 = await client.get("/api/v1/health/live")
        assert r1.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_health_routes_gone(self, client: AsyncClient) -> None:
        for path in [
            "/api/v1/health/healthz",
            "/api/v1/health/health",
            "/api/v1/health/readyz",
        ]:
            r = await client.get(path)
            assert r.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_docs_endpoint_available(self, client: AsyncClient) -> None:
        # Swagger UI may return 200 or 404 depending on config; ensure no 5xx
        r = await client.get("/docs")
        assert r.status_code < 500
