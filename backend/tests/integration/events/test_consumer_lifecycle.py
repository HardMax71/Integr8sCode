import asyncio
import logging

import pytest
from app.core.metrics import EventMetrics
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.xdist_group("kafka_consumers")]

_test_logger = logging.getLogger("test.events.consumer_lifecycle")


@pytest.mark.asyncio
async def test_consumer_run_and_cancel(
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    consumer_config: ConsumerConfig,
    test_settings: Settings,
) -> None:
    """Test consumer run() blocks until cancelled and seek methods work."""
    disp = EventDispatcher(logger=_test_logger)
    consumer = UnifiedConsumer(
        consumer_config,
        dispatcher=disp,
        schema_registry=schema_registry,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
        topics=[KafkaTopic.EXECUTION_EVENTS],
    )

    # Track when consumer is running
    consumer_started = asyncio.Event()

    async def run_with_signal() -> None:
        consumer_started.set()
        await consumer.run()

    task = asyncio.create_task(run_with_signal())

    try:
        # Wait for consumer to start
        await asyncio.wait_for(consumer_started.wait(), timeout=5.0)

        # Exercise seek functions while consumer is running
        await consumer.seek_to_beginning()
        await consumer.seek_to_end()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
