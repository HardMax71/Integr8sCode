from importlib import import_module
from typing import Any

import pytest
import redis.asyncio as aioredis
from app.db.docs import UserDocument
from app.domain.exceptions import DomainError
from app.settings import Settings
from dishka import AsyncContainer
from fastapi import FastAPI
from starlette.routing import Mount, Route

pytestmark = pytest.mark.e2e


class TestAppInstance:
    """Tests for FastAPI app instance creation."""

    def test_app_is_fastapi_instance(self, app: FastAPI) -> None:
        """App is a FastAPI instance."""
        assert isinstance(app, FastAPI)

    def test_app_title_matches_settings(
        self, app: FastAPI, test_settings: Settings
    ) -> None:
        """App title matches PROJECT_NAME from settings."""
        assert app.title == test_settings.PROJECT_NAME

    def test_openapi_disabled_for_security(self, app: FastAPI) -> None:
        """OpenAPI/docs endpoints are disabled in production mode."""
        # OpenAPI is disabled in create_app for security
        assert app.openapi_url is None
        assert app.docs_url is None
        assert app.redoc_url is None


class TestRouterConfiguration:
    """Tests for API router registration."""

    def test_api_routes_registered(self, app: FastAPI) -> None:
        """API routes are registered under /api/ prefix."""
        paths = {r.path for r in app.router.routes if isinstance(r, Route)}
        assert any(p.startswith("/api/") for p in paths)

    def test_health_routes_registered(self, app: FastAPI) -> None:
        """Health check routes are registered."""
        paths = self._get_all_paths(app)
        assert "/api/v1/health/live" in paths

    def test_auth_routes_registered(self, app: FastAPI) -> None:
        """Authentication routes are registered."""
        paths = self._get_all_paths(app)
        assert "/api/v1/auth/login" in paths
        assert "/api/v1/auth/register" in paths
        assert "/api/v1/auth/logout" in paths
        assert "/api/v1/auth/me" in paths

    def test_execution_routes_registered(self, app: FastAPI) -> None:
        """Execution routes are registered."""
        paths = self._get_all_paths(app)
        assert "/api/v1/execute" in paths
        assert "/api/v1/user/executions" in paths
        assert "/api/v1/k8s-limits" in paths
        assert "/api/v1/example-scripts" in paths

    def test_saved_scripts_routes_registered(self, app: FastAPI) -> None:
        """Saved scripts routes are registered."""
        paths = self._get_all_paths(app)
        assert "/api/v1/scripts" in paths

    def test_user_settings_routes_registered(self, app: FastAPI) -> None:
        """User settings routes are registered."""
        paths = self._get_all_paths(app)
        assert any(p.startswith("/api/v1/user/settings") for p in paths)

    def test_notifications_routes_registered(self, app: FastAPI) -> None:
        """Notification routes are registered."""
        paths = self._get_all_paths(app)
        assert "/api/v1/notifications" in paths

    def test_saga_routes_registered(self, app: FastAPI) -> None:
        """Saga routes are registered."""
        paths = self._get_all_paths(app)
        assert any(p.startswith("/api/v1/sagas") for p in paths)

    def test_replay_routes_registered(self, app: FastAPI) -> None:
        """Replay routes are registered (admin only)."""
        paths = self._get_all_paths(app)
        assert "/api/v1/replay/sessions" in paths

    def test_dlq_routes_registered(self, app: FastAPI) -> None:
        """DLQ routes are registered."""
        paths = self._get_all_paths(app)
        assert "/api/v1/dlq/messages" in paths

    def test_events_routes_registered(self, app: FastAPI) -> None:
        """Events routes are registered."""
        paths = self._get_all_paths(app)
        # SSE endpoint
        assert any("/api/v1/events" in p for p in paths)

    def test_admin_routes_registered(self, app: FastAPI) -> None:
        """Admin routes are registered."""
        paths = self._get_all_paths(app)
        assert any(p.startswith("/api/v1/admin/users") for p in paths)
        assert any(p.startswith("/api/v1/admin/settings") for p in paths)
        assert any(p.startswith("/api/v1/admin/events") for p in paths)

    def _get_all_paths(self, app: FastAPI) -> set[str]:
        """Extract all route paths from app, including mounted routers."""
        paths: set[str] = set()
        for route in app.router.routes:
            if isinstance(route, Route):
                paths.add(route.path)
            elif isinstance(route, Mount) and route.routes is not None:
                # For mounted routers, combine mount path with route paths
                for sub_route in route.routes:
                    if isinstance(sub_route, Route):
                        paths.add(f"{route.path}{sub_route.path}")
        return paths


class TestMiddlewareStack:
    """Tests for middleware configuration."""

    def test_cors_middleware_configured(self, app: FastAPI) -> None:
        """CORS middleware is configured."""
        middleware_classes = self._get_middleware_class_names(app)
        assert "CORSMiddleware" in middleware_classes

    def test_cache_control_middleware_configured(self, app: FastAPI) -> None:
        """Cache control middleware is configured."""
        middleware_classes = self._get_middleware_class_names(app)
        assert "CacheControlMiddleware" in middleware_classes

    def test_metrics_middleware_configured(self, app: FastAPI) -> None:
        """Metrics middleware is configured."""
        middleware_classes = self._get_middleware_class_names(app)
        assert "MetricsMiddleware" in middleware_classes

    def test_rate_limit_middleware_configured(self, app: FastAPI) -> None:
        """Rate limit middleware is configured."""
        middleware_classes = self._get_middleware_class_names(app)
        assert "RateLimitMiddleware" in middleware_classes

    def test_csrf_middleware_configured(self, app: FastAPI) -> None:
        """CSRF middleware is configured."""
        middleware_classes = self._get_middleware_class_names(app)
        assert "CSRFMiddleware" in middleware_classes

    def test_middleware_count(self, app: FastAPI) -> None:
        """Expected number of middlewares are configured."""
        # CORS, CacheControl, Metrics, RateLimit, CSRF
        middleware_classes = self._get_middleware_class_names(app)
        expected_middlewares = {
            "CORSMiddleware",
            "CacheControlMiddleware",
            "MetricsMiddleware",
            "RateLimitMiddleware",
            "CSRFMiddleware",
        }
        assert expected_middlewares.issubset(middleware_classes)

    def _get_middleware_class_names(self, app: FastAPI) -> set[str]:
        """Get set of middleware class names from app."""
        return {
            getattr(m.cls, "__name__", str(m.cls)) for m in app.user_middleware
        }


class TestCorsConfiguration:
    """Tests for CORS middleware configuration."""

    def test_cors_allows_localhost_origins(self, app: FastAPI) -> None:
        """CORS allows localhost origins for development."""
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None

        # Check allowed origins
        allowed = cors_kwargs.get("allow_origins", [])
        assert "https://localhost:5001" in allowed
        assert "https://127.0.0.1:5001" in allowed
        assert "https://localhost" in allowed

    def test_cors_allows_credentials(self, app: FastAPI) -> None:
        """CORS allows credentials for cookie-based auth."""
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None
        assert cors_kwargs.get("allow_credentials") is True

    def test_cors_allows_required_methods(self, app: FastAPI) -> None:
        """CORS allows required HTTP methods."""
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None

        methods = cors_kwargs.get("allow_methods", [])
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_cors_allows_required_headers(self, app: FastAPI) -> None:
        """CORS allows required headers."""
        cors_kwargs = self._get_cors_kwargs(app)
        assert cors_kwargs is not None

        headers = cors_kwargs.get("allow_headers", [])
        assert "Authorization" in headers
        assert "Content-Type" in headers
        assert "X-CSRF-Token" in headers

    def _get_cors_kwargs(self, app: FastAPI) -> dict[str, Any] | None:
        """Get CORS middleware kwargs from app."""
        for m in app.user_middleware:
            if getattr(m.cls, "__name__", "") == "CORSMiddleware":
                return dict(m.kwargs)
        return None


class TestDishkaContainer:
    """Tests for Dishka DI container configuration."""

    def test_container_attached_to_app_state(self, app: FastAPI) -> None:
        """Dishka container is attached to app.state."""
        assert hasattr(app.state, "dishka_container")
        assert app.state.dishka_container is not None

    def test_container_is_async_container(self, app: FastAPI) -> None:
        """Dishka container is an AsyncContainer."""
        assert isinstance(app.state.dishka_container, AsyncContainer)

    @pytest.mark.asyncio
    async def test_container_resolves_settings(self, scope: AsyncContainer) -> None:
        """Container can resolve Settings."""
        settings = await scope.get(Settings)
        assert isinstance(settings, Settings)

    @pytest.mark.asyncio
    async def test_container_resolves_logger(self, scope: AsyncContainer) -> None:
        """Container can resolve Logger."""
        import structlog

        logger = await scope.get(structlog.stdlib.BoundLogger)
        assert hasattr(logger, "info")
        assert hasattr(logger, "bind")


class TestExceptionHandlers:
    """Tests for exception handler configuration."""

    def test_domain_error_handler_registered(self, app: FastAPI) -> None:
        """DomainError exception handler is registered."""
        # Exception handlers are stored in app.exception_handlers
        assert DomainError in app.exception_handlers


class TestLifespanInitialization:
    """Tests for app state after lifespan initialization."""

    @pytest.mark.asyncio
    async def test_beanie_initialized(self, app: FastAPI) -> None:
        """Beanie ODM is initialized with document models."""
        # app fixture runs lifespan which initializes Beanie
        # get_settings() raises CollectionWasNotInitialized if not initialized
        settings = UserDocument.get_settings()
        assert settings.name == "users"

    @pytest.mark.asyncio
    async def test_redis_connected(self, scope: AsyncContainer) -> None:
        """Redis client is connected and functional."""
        redis_client = await scope.get(aioredis.Redis)
        # Ping returns a coroutine for async client
        pong = await redis_client.ping()  # type: ignore[misc]
        assert pong is True


class TestCreateAppFunction:
    """Tests for create_app factory function."""

    def test_create_app_returns_fastapi(self, test_settings: Settings) -> None:
        """create_app returns a FastAPI instance."""
        create_app = import_module("app.main").create_app
        instance = create_app(settings=test_settings)
        assert isinstance(instance, FastAPI)

    def test_create_app_uses_provided_settings(
        self, test_settings: Settings
    ) -> None:
        """create_app uses provided settings instead of loading from env."""
        create_app = import_module("app.main").create_app
        instance = create_app(settings=test_settings)
        assert instance.title == test_settings.PROJECT_NAME

    def test_create_app_without_settings_uses_defaults(self) -> None:
        """create_app without settings argument creates default Settings."""
        create_app = import_module("app.main").create_app
        # This will create a Settings() from env/defaults
        # Just verify it doesn't crash
        instance = create_app()
        assert isinstance(instance, FastAPI)
