from importlib import import_module
from typing import Any

import pytest
from app.domain.exceptions import DomainError
from app.main import create_app
from app.settings import Settings
from fastapi import FastAPI
from starlette.routing import Mount, Route

pytestmark = pytest.mark.unit


def _get_all_paths(app: FastAPI) -> set[str]:
    """Extract all route paths from app, including mounted routers."""
    paths: set[str] = set()
    for route in app.router.routes:
        if isinstance(route, Route):
            paths.add(route.path)
        elif isinstance(route, Mount) and route.routes is not None:
            for sub_route in route.routes:
                if isinstance(sub_route, Route):
                    paths.add(f"{route.path}{sub_route.path}")
    return paths


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


class TestRouterConfiguration:
    """Tests for API router registration."""

    def test_api_routes_registered(self, app: FastAPI) -> None:
        paths = {r.path for r in app.router.routes if isinstance(r, Route)}
        assert any(p.startswith("/api/") for p in paths)

    def test_health_routes_registered(self, app: FastAPI) -> None:
        assert "/api/v1/health/live" in _get_all_paths(app)

    def test_auth_routes_registered(self, app: FastAPI) -> None:
        paths = _get_all_paths(app)
        assert "/api/v1/auth/login" in paths
        assert "/api/v1/auth/register" in paths
        assert "/api/v1/auth/logout" in paths
        assert "/api/v1/auth/me" in paths

    def test_execution_routes_registered(self, app: FastAPI) -> None:
        paths = _get_all_paths(app)
        assert "/api/v1/execute" in paths
        assert "/api/v1/user/executions" in paths
        assert "/api/v1/k8s-limits" in paths
        assert "/api/v1/example-scripts" in paths

    def test_saved_scripts_routes_registered(self, app: FastAPI) -> None:
        assert "/api/v1/scripts" in _get_all_paths(app)

    def test_user_settings_routes_registered(self, app: FastAPI) -> None:
        assert any(p.startswith("/api/v1/user/settings") for p in _get_all_paths(app))

    def test_notifications_routes_registered(self, app: FastAPI) -> None:
        assert "/api/v1/notifications" in _get_all_paths(app)

    def test_saga_routes_registered(self, app: FastAPI) -> None:
        assert any(p.startswith("/api/v1/sagas") for p in _get_all_paths(app))

    def test_replay_routes_registered(self, app: FastAPI) -> None:
        assert "/api/v1/replay/sessions" in _get_all_paths(app)

    def test_events_routes_registered(self, app: FastAPI) -> None:
        assert any("/api/v1/events" in p for p in _get_all_paths(app))

    def test_admin_routes_registered(self, app: FastAPI) -> None:
        paths = _get_all_paths(app)
        assert any(p.startswith("/api/v1/admin/users") for p in paths)
        assert any(p.startswith("/api/v1/admin/settings") for p in paths)
        assert any(p.startswith("/api/v1/admin/events") for p in paths)


class TestMiddlewareStack:
    """Tests for middleware configuration."""

    def _get_middleware_class_names(self, app: FastAPI) -> set[str]:
        return {getattr(m.cls, "__name__", str(m.cls)) for m in app.user_middleware}

    def test_cors_middleware_configured(self, app: FastAPI) -> None:
        assert "CORSMiddleware" in self._get_middleware_class_names(app)

    def test_request_size_limit_middleware_configured(self, app: FastAPI) -> None:
        assert "RequestSizeLimitMiddleware" in self._get_middleware_class_names(app)

    def test_cache_control_middleware_configured(self, app: FastAPI) -> None:
        assert "CacheControlMiddleware" in self._get_middleware_class_names(app)

    def test_metrics_middleware_configured(self, app: FastAPI) -> None:
        assert "MetricsMiddleware" in self._get_middleware_class_names(app)

    def test_rate_limit_middleware_configured(self, app: FastAPI) -> None:
        assert "RateLimitMiddleware" in self._get_middleware_class_names(app)

    def test_csrf_middleware_configured(self, app: FastAPI) -> None:
        assert "CSRFMiddleware" in self._get_middleware_class_names(app)

    def test_middleware_count(self, app: FastAPI) -> None:
        expected = {
            "CORSMiddleware", "RequestSizeLimitMiddleware", "CacheControlMiddleware",
            "MetricsMiddleware", "RateLimitMiddleware", "CSRFMiddleware",
        }
        assert expected.issubset(self._get_middleware_class_names(app))


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
        assert isinstance(create_app_fn(), FastAPI)
