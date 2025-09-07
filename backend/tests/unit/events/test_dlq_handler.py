import asyncio
from types import SimpleNamespace

import pytest

from app.events.core.dlq_handler import create_dlq_error_handler, create_immediate_dlq_handler
from app.infrastructure.kafka.events.saga import SagaStartedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


class DummyProducer:
    def __init__(self):
        self.calls = []

    async def send_to_dlq(self, original_event, original_topic, error, retry_count):  # noqa: ANN001
        self.calls.append((original_event.event_id, original_topic, str(error), retry_count))


@pytest.mark.asyncio
async def test_dlq_handler_with_retries():
    p = DummyProducer()
    h = create_dlq_error_handler(p, original_topic="t", max_retries=2)
    e = SagaStartedEvent(saga_id="s", saga_name="n", execution_id="x", initial_event_id="i", metadata=EventMetadata(service_name="a", service_version="1"))
    # Call 1 and 2 should not send to DLQ
    await h(RuntimeError("boom"), e)
    await h(RuntimeError("boom"), e)
    assert len(p.calls) == 0
    # 3rd call triggers DLQ
    await h(RuntimeError("boom"), e)
    assert len(p.calls) == 1
    assert p.calls[0][1] == "t"


@pytest.mark.asyncio
async def test_immediate_dlq_handler():
    p = DummyProducer()
    h = create_immediate_dlq_handler(p, original_topic="t")
    e = SagaStartedEvent(saga_id="s2", saga_name="n", execution_id="x", initial_event_id="i", metadata=EventMetadata(service_name="a", service_version="1"))
    await h(RuntimeError("x"), e)
    assert p.calls and p.calls[0][3] == 0

