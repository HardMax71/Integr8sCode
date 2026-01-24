from importlib import import_module

import pytest
from app.settings import Settings
from dishka import AsyncContainer
from fastapi import FastAPI

pytestmark = pytest.mark.e2e


class TestLifespanContainerSetup:
    """Tests for DI container setup during lifespan."""

    def test_lifespan_container_attached(self, app: FastAPI) -> None:
        """Container is attached to app.state after lifespan starts."""
        assert isinstance(app, FastAPI)
        assert hasattr(app.state, "dishka_container")
        assert app.state.dishka_container is not None

    def test_container_is_async_container(self, app: FastAPI) -> None:
        """Attached container is an AsyncContainer."""
        assert isinstance(app.state.dishka_container, AsyncContainer)


class TestCreateAppAttachesContainer:
    """Tests for create_app container attachment."""

    def test_create_app_attaches_container(
        self, test_settings: Settings
    ) -> None:
        """create_app attaches DI container to app.state."""
        create_app = import_module("app.main").create_app
        app = create_app(settings=test_settings)

        assert isinstance(app, FastAPI)
        assert hasattr(app.state, "dishka_container")
        assert app.state.dishka_container is not None

    def test_create_app_uses_provided_settings(
        self, test_settings: Settings
    ) -> None:
        """create_app uses provided settings in container context."""
        create_app = import_module("app.main").create_app
        app = create_app(settings=test_settings)

        # App title should match settings
        assert app.title == test_settings.PROJECT_NAME


class TestLifespanInitialization:
    """Tests for services initialized during lifespan."""

    @pytest.mark.asyncio
    async def test_beanie_initialized(self, scope: AsyncContainer) -> None:
        """Beanie ODM is initialized during lifespan."""
        from app.core.database_context import Database

        database = await scope.get(Database)
        assert database is not None
        # Database name should be set
        assert database.name is not None

    @pytest.mark.asyncio
    async def test_redis_connected(self, scope: AsyncContainer) -> None:
        """Redis client is connected during lifespan."""
        import redis.asyncio as aioredis

        redis_client = await scope.get(aioredis.Redis)
        # Should be able to ping
        pong = await redis_client.ping()  # type: ignore[misc]
        assert pong is True

    @pytest.mark.asyncio
    async def test_schema_registry_initialized(
        self, scope: AsyncContainer
    ) -> None:
        """Schema registry is initialized during lifespan."""
        from app.events.schema.schema_registry import SchemaRegistryManager

        registry = await scope.get(SchemaRegistryManager)
        assert registry is not None

    @pytest.mark.asyncio
    async def test_sse_bridge_available(self, scope: AsyncContainer) -> None:
        """SSE Kafka bridge is available after lifespan."""
        from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge

        bridge = await scope.get(SSEKafkaRedisBridge)
        assert bridge is not None

    @pytest.mark.asyncio
    async def test_event_store_consumer_available(
        self, scope: AsyncContainer
    ) -> None:
        """Event store consumer is available after lifespan."""
        from app.events.event_store_consumer import EventStoreConsumer

        consumer = await scope.get(EventStoreConsumer)
        assert consumer is not None
