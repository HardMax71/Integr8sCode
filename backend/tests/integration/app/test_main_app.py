from importlib import import_module

import pytest
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app.core.correlation import CorrelationMiddleware
from app.core.middlewares import (
    CacheControlMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
)

pytestmark = pytest.mark.integration


def test_create_app_real_instance(app: FastAPI) -> None:
    assert isinstance(app, FastAPI)

    # Verify API routes are configured
    paths = {r.path for r in app.router.routes if isinstance(r, Route)}
    assert any(p.startswith("/api/") for p in paths)

    # Verify required middlewares are actually present in the stack
    middleware_class_names = {getattr(m.cls, "__name__", str(m.cls)) for m in app.user_middleware}

    # Check that all required middlewares are configured
    assert "CORSMiddleware" in middleware_class_names, "CORS middleware not configured"
    assert "CorrelationMiddleware" in middleware_class_names, "Correlation middleware not configured"
    assert "RequestSizeLimitMiddleware" in middleware_class_names, "Request size limit middleware not configured"
    assert "CacheControlMiddleware" in middleware_class_names, "Cache control middleware not configured"
    assert "MetricsMiddleware" in middleware_class_names, "Metrics middleware not configured"
    assert "RateLimitMiddleware" in middleware_class_names, "Rate limit middleware not configured"


def test_create_app_function_constructs(app: FastAPI) -> None:
    # Sanity: calling create_app returns a FastAPI instance (lazy import)
    inst = import_module("app.main").create_app()
    assert isinstance(inst, FastAPI)
