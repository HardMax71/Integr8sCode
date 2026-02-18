import pytest
import redis.asyncio as aioredis
from app.db.docs import UserDocument
from app.settings import Settings
from dishka import AsyncContainer
from fastapi import FastAPI

pytestmark = pytest.mark.e2e


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


class TestLifespanInitialization:
    """Tests for app state after lifespan initialization."""

    @pytest.mark.asyncio
    async def test_beanie_initialized(self, app: FastAPI) -> None:
        """Beanie ODM is initialized with document models."""
        settings = UserDocument.get_settings()
        assert settings.name == "users"

    @pytest.mark.asyncio
    async def test_redis_connected(self, scope: AsyncContainer) -> None:
        """Redis client is connected and functional."""
        redis_client = await scope.get(aioredis.Redis)
        pong = await redis_client.ping()  # type: ignore[misc]
        assert pong is True
