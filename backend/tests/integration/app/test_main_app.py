from importlib import import_module

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from starlette.routing import Route

pytestmark = pytest.mark.integration


def test_create_app_real_instance(app: FastAPI) -> None:
    assert isinstance(app, FastAPI)

    # Verify API routes are configured (narrow BaseRoute to Route for path access)
    paths = {r.path for r in app.router.routes if isinstance(r, Route)}
    assert any(p.startswith("/api/") for p in paths)

    # Verify middleware stack has expected count (6 custom middlewares)
    assert len(app.user_middleware) >= 6, "Expected at least 6 middlewares configured"


@pytest.mark.asyncio
async def test_middlewares_behavior(client: AsyncClient) -> None:
    """Test middleware behavior via HTTP - the proper way to verify middleware config."""
    # CORS middleware: responds to preflight OPTIONS with CORS headers for allowed origins
    allowed_origin = "https://localhost:5001"
    resp = await client.options(
        "/api/v1/health",
        headers={"Origin": allowed_origin, "Access-Control-Request-Method": "GET"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == allowed_origin

    # Correlation middleware: adds correlation ID header to responses
    resp = await client.get("/api/v1/health")
    assert "x-correlation-id" in resp.headers

    # Cache-Control middleware: adds cache headers
    assert "cache-control" in resp.headers


def test_create_app_function_constructs(app: FastAPI) -> None:
    # Sanity: calling create_app returns a FastAPI instance (lazy import)
    inst = import_module("app.main").create_app()
    assert isinstance(inst, FastAPI)
