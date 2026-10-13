from importlib import import_module
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from app.domain.exceptions import DomainError
from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.unit


def _get_all_paths(app: FastAPI) -> set[str]:
    """Extract all API paths the app exposes, including included routers."""
    return set(app.openapi()["paths"])


@pytest.fixture(scope="module")
def app(test_settings: Settings) -> FastAPI:
    """Lightweight app without lifespan — no MongoDB, Kafka, or Redis."""
    return create_app(settings=test_settings)


class TestAppInstance:
    """Tests for FastAPI app instance creation."""

    def test_app_is_fastapi_instance(self, app: FastAPI) -> None:
        assert isinstance(app, FastAPI)

    def test_app_title_matches_settings(self, app: FastAPI, test_settings: Settings) -> None:
        assert app.title == test_settings.PROJECT_NAME

    def test_openapi_disabled_for_security(self, app: FastAPI) -> None:
        assert app.openapi_url is None
        assert app.docs_url is None
        assert app.redoc_url is None


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health/live",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/execute",
        "/api/v1/user/executions",
        "/api/v1/k8s-limits",
        "/api/v1/example-scripts",
        "/api/v1/scripts",
        "/api/v1/user/settings/",
        "/api/v1/notifications",
        "/api/v1/sagas/",
        "/api/v1/replay/sessions",
        "/api/v1/events/executions/{execution_id}",
        "/api/v1/admin/users/",
        "/api/v1/admin/settings/",
        "/api/v1/admin/events/browse",
    ],
)
def test_route_is_registered(app: FastAPI, path: str) -> None:
    assert path in _get_all_paths(app)


@pytest.mark.parametrize(
    "middleware",
    [
        "CORSMiddleware",
        "RequestSizeLimitMiddleware",
        "CacheControlMiddleware",
        "RateLimitMiddleware",
        "CSRFMiddleware",
    ],
)
def test_middleware_is_installed(app: FastAPI, middleware: str) -> None:
    assert middleware in {getattr(m.cls, "__name__", str(m.cls)) for m in app.user_middleware}


class TestCorsConfiguration:
    """Tests for CORS middleware configuration."""

    def _get_cors_kwargs(self, app: FastAPI) -> dict[str, Any] | None:
        for m in app.user_middleware:
            if getattr(m.cls, "__name__", "") == "CORSMiddleware":
                return dict(m.kwargs)
        return None

    def test_cors_allows_localhost_origins(self, app: FastAPI) -> None:
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None
        allowed = cors_kwargs.get("allow_origins", [])
        assert "https://localhost:5001" in allowed
        assert "https://127.0.0.1:5001" in allowed
        assert "https://localhost" in allowed

    def test_cors_allows_credentials(self, app: FastAPI) -> None:
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None
        assert cors_kwargs.get("allow_credentials") is True

    def test_cors_allows_required_methods(self, app: FastAPI) -> None:
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None
        methods = cors_kwargs.get("allow_methods", [])
        for m in ("GET", "POST", "PUT", "DELETE"):
            assert m in methods

    def test_cors_allows_required_headers(self, app: FastAPI) -> None:
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None
        headers = cors_kwargs.get("allow_headers", [])
        for h in ("Authorization", "Content-Type", "X-CSRF-Token"):
            assert h in headers


class TestExceptionHandlers:
    """Tests for exception handler configuration."""

    def test_domain_error_handler_registered(self, app: FastAPI) -> None:
        assert DomainError in app.exception_handlers


class TestCreateAppFunction:
    """Tests for create_app factory function."""

    def test_create_app_returns_fastapi(self, test_settings: Settings) -> None:
        create_app_fn = import_module("app.main").create_app
        assert isinstance(create_app_fn(settings=test_settings), FastAPI)

    def test_create_app_uses_provided_settings(self, test_settings: Settings) -> None:
        create_app_fn = import_module("app.main").create_app
        assert create_app_fn(settings=test_settings).title == test_settings.PROJECT_NAME

    def test_create_app_without_settings_uses_defaults(self) -> None:
        create_app_fn = import_module("app.main").create_app
        # config.toml sets an OTLP endpoint, and the real setup would install process-wide OTel providers
        with patch("app.main.setup_metrics"), patch("app.main.setup_log_exporter"):
            assert isinstance(create_app_fn(), FastAPI)
