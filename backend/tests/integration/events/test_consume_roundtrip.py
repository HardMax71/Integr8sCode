import asyncio
import logging

import pytest
from app.core.metrics import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.core import ConsumerConfig, UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.xdist_group("kafka_consumers")]

_test_logger = logging.getLogger("test.events.consume_roundtrip")


@pytest.mark.asyncio
async def test_produce_consume_roundtrip(
    scope: AsyncContainer,
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    consumer_config: ConsumerConfig,
    test_settings: Settings,
) -> None:
    # Ensure schemas are registered
    await initialize_event_schemas(schema_registry)

    # Real producer from DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)

    # Build a consumer that handles EXECUTION_REQUESTED
    dispatcher = EventDispatcher(logger=_test_logger)
    received = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def _handle(_event: DomainEvent) -> None:
        received.set()

    consumer = UnifiedConsumer(
        consumer_config,
        dispatcher,
        schema_registry=schema_registry,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
        topics=[KafkaTopic.EXECUTION_EVENTS],
    )

    # Start consumer as background task
    consumer_task = asyncio.create_task(consumer.run())

    try:
        # Produce a request event
        execution_id = f"exec-{consumer_config.group_id}"
        evt = make_execution_requested_event(execution_id=execution_id)
        await producer.produce(evt, key=execution_id)

        # Wait for the handler to be called
        await asyncio.wait_for(received.wait(), timeout=10.0)
    finally:
        consumer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer_task
