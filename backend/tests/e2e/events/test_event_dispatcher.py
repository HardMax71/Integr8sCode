import asyncio
import logging
import uuid

import pytest
from aiokafka import AIOKafkaConsumer
from app.core.metrics import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.xdist_group("kafka_consumers")]

_test_logger = logging.getLogger("test.events.event_dispatcher")


@pytest.mark.asyncio
async def test_dispatcher_with_multiple_handlers(scope: AsyncContainer) -> None:
    # Ensure schema registry is ready
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    event_metrics: EventMetrics = await scope.get(EventMetrics)
    await initialize_event_schemas(registry)

    # Build dispatcher with two handlers for the same event
    dispatcher = EventDispatcher(logger=_test_logger)
    h1_called = asyncio.Event()
    h2_called = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def h1(_e: DomainEvent) -> None:
        h1_called.set()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def h2(_e: DomainEvent) -> None:
        h2_called.set()

    group_id = f"dispatcher-it.{uuid.uuid4().hex[:6]}"

    # Create AIOKafkaConsumer directly for test
    topic = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.EXECUTION_EVENTS}"
    kafka_consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    await kafka_consumer.start()

    handler = UnifiedConsumer(
        event_dispatcher=dispatcher,
        schema_registry=registry,
        logger=_test_logger,
        event_metrics=event_metrics,
        group_id=group_id,
    )

    # Produce a request event via DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    evt = make_execution_requested_event(execution_id=f"exec-{uuid.uuid4().hex[:8]}")
    await producer.produce(evt, key="k")

    try:
        async def consume_until_handled() -> None:
            async for msg in kafka_consumer:
                await handler.handle(msg)
                await kafka_consumer.commit()
                if h1_called.is_set() and h2_called.is_set():
                    break

        await asyncio.wait_for(consume_until_handled(), timeout=10.0)
    finally:
        await kafka_consumer.stop()
