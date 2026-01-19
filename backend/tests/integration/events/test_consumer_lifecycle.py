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
async def test_consumer_start_status_seek_and_stop(
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    consumer_config: ConsumerConfig,
    test_settings: Settings,
) -> None:
    disp = EventDispatcher(logger=_test_logger)
    c = UnifiedConsumer(
        consumer_config,
        event_dispatcher=disp,
        schema_registry=schema_registry,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    await c.start([KafkaTopic.EXECUTION_EVENTS])
    try:
        st = c.get_status()
        assert st.state == "running"
        # Exercise seek functions; don't force specific partition offsets
        await c.seek_to_beginning()
        await c.seek_to_end()
        # No need to sleep; just ensure we can call seek APIs while running
    finally:
        await c.stop()
