import logging
from collections.abc import Callable

import backoff
import pytest
from app.core.database_context import Database
from app.domain.enums.auth import LoginMethod
from app.domain.enums.kafka import KafkaTopic
from app.events.core import UnifiedProducer
from app.events.event_store import EventStore
from app.events.event_store_consumer import EventStoreConsumer, create_event_store_consumer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.settings import Settings
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.events.event_store_consumer")


@pytest.mark.asyncio
async def test_event_store_consumer_stores_events(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    # Ensure schemas
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    await initialize_event_schemas(registry)

    # Resolve DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    db: Database = await scope.get(Database)
    store: EventStore = await scope.get(EventStore)
    settings: Settings = await scope.get(Settings)

    # Build an event
    ev = UserLoggedInEvent(
        user_id=unique_id("u-"),
        login_method=LoginMethod.PASSWORD,
        metadata=AvroEventMetadata(service_name="tests", service_version="1.0.0"),
    )

    # Create a tuned consumer (fast batch timeout) limited to user-events
    consumer: EventStoreConsumer = create_event_store_consumer(
        event_store=store,
        topics=[KafkaTopic.USER_EVENTS],
        schema_registry_manager=registry,
        settings=settings,
        logger=_test_logger,
        producer=producer,
        batch_size=10,
        batch_timeout_seconds=0.5,
    )

    # Start the consumer and publish
    async with consumer:
        await producer.produce(ev, key=ev.metadata.user_id or "u")

        # Wait until the event is persisted in Mongo
        coll = db.get_collection("events")

        @backoff.on_exception(backoff.constant, AssertionError, max_time=12.0, interval=0.2)
        async def _wait_exists() -> None:
            doc = await coll.find_one({"event_id": ev.event_id})
            assert doc is not None

        await _wait_exists()
