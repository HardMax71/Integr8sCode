from importlib import import_module

import pytest
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.correlation import CorrelationMiddleware
from app.core.middlewares import (
    CacheControlMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)

pytestmark = pytest.mark.unit


def test_create_app_real_instance(app) -> None:  # type: ignore[valid-type]
    assert isinstance(app, FastAPI)

    # Verify API routes are configured
    paths = {r.path for r in app.router.routes}
    assert any(p.startswith("/api/") for p in paths)

    # Verify required middlewares are actually present in the stack
    middleware_classes = {m.cls for m in app.user_middleware}

    # Check that all required middlewares are configured
    assert CORSMiddleware in middleware_classes, "CORS middleware not configured"
    assert CorrelationMiddleware in middleware_classes, "Correlation middleware not configured"
    assert RequestSizeLimitMiddleware in middleware_classes, "Request size limit middleware not configured"
    assert CacheControlMiddleware in middleware_classes, "Cache control middleware not configured"
    assert MetricsMiddleware in middleware_classes, "Metrics middleware not configured"
    assert RateLimitMiddleware in middleware_classes, "Rate limit middleware not configured"


def test_create_app_function_constructs(app) -> None:  # type: ignore[valid-type]
    # Sanity: calling create_app returns a FastAPI instance (lazy import)
    inst = import_module("app.main").create_app()
    assert isinstance(inst, FastAPI)
