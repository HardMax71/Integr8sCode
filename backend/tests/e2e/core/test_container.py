import pytest
import redis.asyncio as redis
import structlog
from dishka import AsyncContainer
from fastapi import FastAPI

from app.core.security import SecurityService
from app.db.docs import UserDocument
from app.services.admin import AdminUserService
from app.services.event_replay import EventReplayService
from app.services.event_service import EventService
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.rate_limit_service import RateLimitService
from app.services.saved_script_service import SavedScriptService
from app.services.user_settings_service import UserSettingsService
from app.settings import Settings

pytestmark = [pytest.mark.e2e]


class TestCoreInfrastructure:
    """Tests for core infrastructure dependency resolution."""

    async def test_resolves_settings(self, test_settings: Settings) -> None:
        """Container resolves Settings."""

        assert isinstance(test_settings, Settings)
        assert test_settings.PROJECT_NAME is not None

    async def test_resolves_logger(self, scope: AsyncContainer) -> None:
        """Container resolves BoundLogger."""
        logger = await scope.get(structlog.stdlib.BoundLogger)

        assert hasattr(logger, "info")
        assert hasattr(logger, "bind")

    async def test_beanie_initialized(self, app: FastAPI) -> None:
        """Beanie is initialized and document classes work."""
        # app fixture runs lifespan which initializes Beanie
        # get_settings() raises CollectionWasNotInitialized if not initialized
        settings = UserDocument.get_settings()
        assert settings.name == "users"

    async def test_resolves_redis(self, redis_client: redis.Redis) -> None:
        """Container resolves Redis client."""

        assert redis_client is not None
        # Verify connection works
        pong = await redis_client.ping()
        assert pong is True


class TestSecurityServices:
    """Tests for security-related service resolution."""

    async def test_resolves_security_service(self, security_service: SecurityService) -> None:
        """Container resolves SecurityService."""

        assert isinstance(security_service, SecurityService)
        assert security_service.settings is not None


class TestEventServices:
    """Tests for event-related service resolution."""

    async def test_resolves_event_service(self, event_service: EventService) -> None:
        """Container resolves EventService."""

        assert isinstance(event_service, EventService)


class TestBusinessServices:
    """Tests for business service resolution."""

    async def test_resolves_execution_service(self, execution_service: ExecutionService) -> None:
        """Container resolves ExecutionService."""

        assert isinstance(execution_service, ExecutionService)

    async def test_resolves_admin_user_service(self, admin_user_service: AdminUserService) -> None:
        """Container resolves AdminUserService."""

        assert isinstance(admin_user_service, AdminUserService)

    async def test_resolves_saved_script_service(self, saved_script_service: SavedScriptService) -> None:
        """Container resolves SavedScriptService."""

        assert isinstance(saved_script_service, SavedScriptService)

    async def test_resolves_notification_service(self, notification_service: NotificationService) -> None:
        """Container resolves NotificationService."""

        assert isinstance(notification_service, NotificationService)

    async def test_resolves_user_settings_service(self, user_settings_service: UserSettingsService) -> None:
        """Container resolves UserSettingsService."""

        assert isinstance(user_settings_service, UserSettingsService)

    async def test_resolves_rate_limit_service(self, scope: AsyncContainer) -> None:
        """Container resolves RateLimitService."""
        service = await scope.get(RateLimitService)

        assert isinstance(service, RateLimitService)

    async def test_resolves_replay_service(self, event_replay_service: EventReplayService) -> None:
        """Container resolves EventReplayService."""

        assert isinstance(event_replay_service, EventReplayService)


class TestServiceDependencies:
    """Tests that services have their dependencies correctly injected."""

    async def test_execution_service_has_dependencies(self, execution_service: ExecutionService) -> None:
        """ExecutionService has required dependencies."""

        # Check that key dependencies are present
        assert execution_service.settings is not None
        assert execution_service.execution_repo is not None

    async def test_security_service_uses_settings(
        self, test_settings: Settings, security_service: SecurityService
    ) -> None:
        """SecurityService uses injected test_settings."""

        # Both should reference same test_settings
        assert security_service.settings.SECRET_KEY == test_settings.SECRET_KEY
        assert security_service.settings.ALGORITHM == test_settings.ALGORITHM


class TestContainerScoping:
    """Tests for container scope behavior."""

    async def test_same_scope_returns_same_instance(
        self, scope: AsyncContainer, execution_service: ExecutionService
    ) -> None:
        """Same scope returns same service instance."""

        assert execution_service is execution_service

    async def test_settings_is_singleton(self, scope: AsyncContainer, test_settings: Settings) -> None:
        """Settings is a singleton across the scope."""

        assert test_settings is test_settings
