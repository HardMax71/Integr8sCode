import logging
from uuid import uuid4

import pytest
from app.core.metrics import EventMetrics
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings
from dishka import AsyncContainer

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.xdist_group("kafka_consumers")]

_test_logger = logging.getLogger("test.events.consumer_lifecycle")


@pytest.mark.asyncio
async def test_consumer_start_status_seek_and_stop(scope: AsyncContainer) -> None:
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    event_metrics: EventMetrics = await scope.get(EventMetrics)
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-consumer-{uuid4().hex[:6]}",
    )
    disp = EventDispatcher(logger=_test_logger)
    c = UnifiedConsumer(
        cfg,
        event_dispatcher=disp,
        schema_registry=registry,
        settings=settings,
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
