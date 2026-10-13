import pytest
import redis.asyncio as redis
from dishka import AsyncContainer
from fastapi import FastAPI

from app.db.docs import UserDocument
from app.settings import Settings

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

    async def test_container_resolves_settings(self, test_settings: Settings) -> None:
        """Container can resolve Settings."""
        assert isinstance(test_settings, Settings)

    async def test_container_resolves_logger(self, scope: AsyncContainer) -> None:
        """Container can resolve Logger."""
        import structlog

        logger = await scope.get(structlog.stdlib.BoundLogger)
        assert hasattr(logger, "info")
        assert hasattr(logger, "bind")


class TestLifespanInitialization:
    """Tests for app state after lifespan initialization."""

    async def test_beanie_initialized(self, app: FastAPI) -> None:
        """Beanie ODM is initialized with document models."""
        settings = UserDocument.get_settings()
        assert settings.name == "users"

    async def test_redis_connected(self, redis_client: redis.Redis) -> None:
        """Redis client is connected and functional."""
        pong = await redis_client.ping()
        assert pong is True
