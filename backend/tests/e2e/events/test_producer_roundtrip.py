import logging
from uuid import uuid4

import pytest
from app.events.core import ProducerMetrics, UnifiedProducer
from app.infrastructure.kafka.mappings import get_topic_for_event
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.producer_roundtrip")


@pytest.mark.asyncio
async def test_unified_producer_produce_and_send_to_dlq(scope: AsyncContainer) -> None:
    # Get producer and metrics from DI
    prod: UnifiedProducer = await scope.get(UnifiedProducer)
    metrics: ProducerMetrics = await scope.get(ProducerMetrics)

    initial_sent = metrics.messages_sent

    # Produce an event
    ev = make_execution_requested_event(execution_id=f"exec-{uuid4().hex[:8]}")
    await prod.produce(ev)

    # Exercise send_to_dlq path
    topic = get_topic_for_event(ev.event_type)
    await prod.send_to_dlq(ev, original_topic=topic, error=RuntimeError("forced"), retry_count=1)

    # Verify metrics are being tracked
    assert metrics.messages_sent >= initial_sent + 2
