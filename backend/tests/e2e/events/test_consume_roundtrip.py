import asyncio
import logging
import uuid

import pytest
from app.core.metrics import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.xdist_group("kafka_consumers")]

_test_logger = logging.getLogger("test.events.consume_roundtrip")


@pytest.mark.asyncio
async def test_produce_consume_roundtrip(scope: AsyncContainer) -> None:
    # Ensure schemas are registered
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    event_metrics: EventMetrics = await scope.get(EventMetrics)
    await initialize_event_schemas(registry)

    # Real producer from DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)

    # Build a consumer that handles EXECUTION_REQUESTED
    dispatcher = EventDispatcher(logger=_test_logger)
    received = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def _handle(_event: DomainEvent) -> None:
        received.set()

    group_id = f"test-consumer.{uuid.uuid4().hex[:6]}"
    config = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )

    consumer = UnifiedConsumer(
        config,
        dispatcher,
        schema_registry=registry,
        settings=settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    await consumer.start([KafkaTopic.EXECUTION_EVENTS])

    try:
        # Produce a request event
        execution_id = f"exec-{uuid.uuid4().hex[:8]}"
        evt = make_execution_requested_event(execution_id=execution_id)
        await producer.produce(evt, key=execution_id)

        # Wait for the handler to be called
        await asyncio.wait_for(received.wait(), timeout=10.0)
    finally:
        await consumer.stop()
