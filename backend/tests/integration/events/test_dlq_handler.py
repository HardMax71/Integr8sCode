import pytest

from app.events.core import create_dlq_error_handler, create_immediate_dlq_handler
from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.saga import SagaStartedEvent

pytestmark = [pytest.mark.integration, pytest.mark.kafka]


@pytest.mark.asyncio
async def test_dlq_handler_with_retries(scope, monkeypatch):  # type: ignore[valid-type]
    p: UnifiedProducer = await scope.get(UnifiedProducer)
    calls: list[tuple[str | None, str, str, int]] = []

    async def _record_send_to_dlq(original_event, original_topic, error, retry_count):  # noqa: ANN001
        calls.append((original_event.event_id, original_topic, str(error), retry_count))

    monkeypatch.setattr(p, "send_to_dlq", _record_send_to_dlq)
    h = create_dlq_error_handler(p, original_topic="t", max_retries=2)
    e = SagaStartedEvent(saga_id="s", saga_name="n", execution_id="x", initial_event_id="i",
                         metadata=AvroEventMetadata(service_name="a", service_version="1"))
    # Call 1 and 2 should not send to DLQ
    await h(RuntimeError("boom"), e)
    await h(RuntimeError("boom"), e)
    assert len(calls) == 0
    # 3rd call triggers DLQ
    await h(RuntimeError("boom"), e)
    assert len(calls) == 1
    assert calls[0][1] == "t"


@pytest.mark.asyncio
async def test_immediate_dlq_handler(scope, monkeypatch):  # type: ignore[valid-type]
    p: UnifiedProducer = await scope.get(UnifiedProducer)
    calls: list[tuple[str | None, str, str, int]] = []

    async def _record_send_to_dlq(original_event, original_topic, error, retry_count):  # noqa: ANN001
        calls.append((original_event.event_id, original_topic, str(error), retry_count))

    monkeypatch.setattr(p, "send_to_dlq", _record_send_to_dlq)
    h = create_immediate_dlq_handler(p, original_topic="t")
    e = SagaStartedEvent(saga_id="s2", saga_name="n", execution_id="x", initial_event_id="i",
                         metadata=AvroEventMetadata(service_name="a", service_version="1"))
    await h(RuntimeError("x"), e)
    assert calls and calls[0][3] == 0
