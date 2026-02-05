import logging
from uuid import uuid4

import pytest
from app.events.core import EventPublisher
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.producer_roundtrip")


@pytest.mark.asyncio
async def test_unified_producer_produce_and_send_to_dlq(
    scope: AsyncContainer,
) -> None:
    prod: EventPublisher = await scope.get(EventPublisher)

    ev = make_execution_requested_event(execution_id=f"exec-{uuid4().hex[:8]}")
    await prod.publish(ev, key=ev.execution_id)

    # Exercise send_to_dlq path — should not raise
    # Topic is derived from event class via BaseEvent.topic()
    topic = type(ev).topic()
    await prod.send_to_dlq(ev, original_topic=topic, error=RuntimeError("forced"), retry_count=1)
