import logging
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer
from app.core.metrics import EventMetrics
from app.events.core import ProducerMetrics, UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.mappings import get_topic_for_event
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.producer_roundtrip")


@pytest.mark.asyncio
async def test_unified_producer_start_produce_send_to_dlq_stop(
    scope: AsyncContainer, test_settings: Settings
) -> None:
    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    event_metrics: EventMetrics = await scope.get(EventMetrics)

    aiokafka_producer = AIOKafkaProducer(
        bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id=f"{test_settings.SERVICE_NAME}-producer-test",
        acks="all",
        compression_type="gzip",
        max_batch_size=16384,
        linger_ms=10,
        enable_idempotence=True,
    )

    # Start the underlying producer (lifecycle managed externally, not by UnifiedProducer)
    await aiokafka_producer.start()
    try:
        prod = UnifiedProducer(
            producer=aiokafka_producer,
            metrics=ProducerMetrics(),
            schema_registry=schema,
            settings=test_settings,
            logger=_test_logger,
            event_metrics=event_metrics,
        )

        ev = make_execution_requested_event(execution_id=f"exec-{uuid4().hex[:8]}")
        await prod.produce(ev)

        # Exercise send_to_dlq path
        topic = str(get_topic_for_event(ev.event_type))
        await prod.send_to_dlq(ev, original_topic=topic, error=RuntimeError("forced"), retry_count=1)
    finally:
        await aiokafka_producer.stop()
