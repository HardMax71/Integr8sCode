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

_test_logger = logging.getLogger("test.events.event_dispatcher")


@pytest.mark.asyncio
async def test_dispatcher_with_multiple_handlers(
    scope: AsyncContainer,
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    consumer_config: ConsumerConfig,
    test_settings: Settings,
) -> None:
    # Ensure schema registry is ready
    await initialize_event_schemas(schema_registry)

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

    # Real consumer against execution-events
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

    # Produce a request event via DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    evt = make_execution_requested_event(execution_id=f"exec-{consumer_config.group_id}")
    await producer.produce(evt, key="k")

    try:
        await asyncio.wait_for(asyncio.gather(h1_called.wait(), h2_called.wait()), timeout=10.0)
    finally:
        consumer_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer_task
