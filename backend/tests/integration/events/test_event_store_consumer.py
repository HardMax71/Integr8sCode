import logging
import uuid

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

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.kafka,
    pytest.mark.mongodb,
    pytest.mark.xdist_group("kafka_consumers"),
]

_test_logger = logging.getLogger("test.events.event_store_consumer")


@pytest.mark.asyncio
async def test_event_store_consumer_stores_events(scope) -> None:  # type: ignore[valid-type]
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
        user_id=f"u-{uuid.uuid4().hex[:6]}",
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
        from tests.helpers.eventually import eventually

        async def _exists() -> None:
            doc = await coll.find_one({"event_id": ev.event_id})
            assert doc is not None

        await eventually(_exists, timeout=12.0, interval=0.2)
