import pytest
import structlog
import redis.asyncio as aioredis
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
from dishka import AsyncContainer
from fastapi import FastAPI

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


class TestCoreInfrastructure:
    """Tests for core infrastructure dependency resolution."""

    @pytest.mark.asyncio
    async def test_resolves_settings(self, scope: AsyncContainer) -> None:
        """Container resolves Settings."""
        settings = await scope.get(Settings)

        assert isinstance(settings, Settings)
        assert settings.PROJECT_NAME is not None

    @pytest.mark.asyncio
    async def test_resolves_logger(self, scope: AsyncContainer) -> None:
        """Container resolves BoundLogger."""
        logger = await scope.get(structlog.stdlib.BoundLogger)

        assert isinstance(logger, structlog.stdlib.BoundLogger)

    @pytest.mark.asyncio
    async def test_beanie_initialized(self, app: FastAPI) -> None:
        """Beanie is initialized and document classes work."""
        # app fixture runs lifespan which initializes Beanie
        # get_settings() raises CollectionWasNotInitialized if not initialized
        settings = UserDocument.get_settings()
        assert settings.name == "users"

    @pytest.mark.asyncio
    async def test_resolves_redis(self, scope: AsyncContainer) -> None:
        """Container resolves Redis client."""
        redis_client = await scope.get(aioredis.Redis)

        assert redis_client is not None
        # Verify connection works
        pong = await redis_client.ping()  # type: ignore[misc]
        assert pong is True


class TestSecurityServices:
    """Tests for security-related service resolution."""

    @pytest.mark.asyncio
    async def test_resolves_security_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves SecurityService."""
        security = await scope.get(SecurityService)

        assert isinstance(security, SecurityService)
        assert security.settings is not None


class TestEventServices:
    """Tests for event-related service resolution."""

    @pytest.mark.asyncio
    async def test_resolves_event_service(self, scope: AsyncContainer) -> None:
        """Container resolves EventService."""
        service = await scope.get(EventService)

        assert isinstance(service, EventService)


class TestBusinessServices:
    """Tests for business service resolution."""

    @pytest.mark.asyncio
    async def test_resolves_execution_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves ExecutionService."""
        service = await scope.get(ExecutionService)

        assert isinstance(service, ExecutionService)

    @pytest.mark.asyncio
    async def test_resolves_admin_user_service(self, scope: AsyncContainer) -> None:
        """Container resolves AdminUserService."""
        service = await scope.get(AdminUserService)

        assert isinstance(service, AdminUserService)

    @pytest.mark.asyncio
    async def test_resolves_saved_script_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves SavedScriptService."""
        service = await scope.get(SavedScriptService)

        assert isinstance(service, SavedScriptService)

    @pytest.mark.asyncio
    async def test_resolves_notification_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves NotificationService."""
        service = await scope.get(NotificationService)

        assert isinstance(service, NotificationService)

    @pytest.mark.asyncio
    async def test_resolves_user_settings_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves UserSettingsService."""
        service = await scope.get(UserSettingsService)

        assert isinstance(service, UserSettingsService)

    @pytest.mark.asyncio
    async def test_resolves_rate_limit_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves RateLimitService."""
        service = await scope.get(RateLimitService)

        assert isinstance(service, RateLimitService)

    @pytest.mark.asyncio
    async def test_resolves_replay_service(
        self, scope: AsyncContainer
    ) -> None:
        """Container resolves EventReplayService."""
        service = await scope.get(EventReplayService)

        assert isinstance(service, EventReplayService)


class TestServiceDependencies:
    """Tests that services have their dependencies correctly injected."""

    @pytest.mark.asyncio
    async def test_execution_service_has_dependencies(
        self, scope: AsyncContainer
    ) -> None:
        """ExecutionService has required dependencies."""
        service = await scope.get(ExecutionService)

        # Check that key dependencies are present
        assert service.settings is not None
        assert service.execution_repo is not None

    @pytest.mark.asyncio
    async def test_security_service_uses_settings(
        self, scope: AsyncContainer
    ) -> None:
        """SecurityService uses injected settings."""
        settings = await scope.get(Settings)
        security = await scope.get(SecurityService)

        # Both should reference same settings
        assert security.settings.SECRET_KEY == settings.SECRET_KEY
        assert security.settings.ALGORITHM == settings.ALGORITHM


class TestContainerScoping:
    """Tests for container scope behavior."""

    @pytest.mark.asyncio
    async def test_same_scope_returns_same_instance(
        self, scope: AsyncContainer
    ) -> None:
        """Same scope returns same service instance."""
        service1 = await scope.get(ExecutionService)
        service2 = await scope.get(ExecutionService)

        assert service1 is service2

    @pytest.mark.asyncio
    async def test_settings_is_singleton(self, scope: AsyncContainer) -> None:
        """Settings is a singleton across the scope."""
        settings1 = await scope.get(Settings)
        settings2 = await scope.get(Settings)

        assert settings1 is settings2
