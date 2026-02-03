import logging

import pytest
from app.domain.events.typed import DomainEvent, EventMetadata, SagaStartedEvent
from app.events.core import UnifiedProducer, create_dlq_error_handler, create_immediate_dlq_handler
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.dlq_handler")


@pytest.mark.asyncio
async def test_dlq_handler_with_retries(scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch) -> None:
    p: UnifiedProducer = await scope.get(UnifiedProducer)
    calls: list[tuple[str | None, str, str, int]] = []

    async def _record_send_to_dlq(
        original_event: DomainEvent, original_topic: str, error: Exception, retry_count: int
    ) -> None:
        calls.append((original_event.event_id, original_topic, str(error), retry_count))

    monkeypatch.setattr(p, "send_to_dlq", _record_send_to_dlq)
    h = create_dlq_error_handler(p, max_retries=2, logger=_test_logger)
    e = SagaStartedEvent(
        saga_id="s",
        saga_name="n",
        execution_id="x",
        initial_event_id="i",
        metadata=EventMetadata(service_name="a", service_version="1"),
    )
    # Call 1 and 2 should not send to DLQ
    await h(RuntimeError("boom"), e, "test-topic")
    await h(RuntimeError("boom"), e, "test-topic")
    assert len(calls) == 0
    # 3rd call triggers DLQ
    await h(RuntimeError("boom"), e, "test-topic")
    assert len(calls) == 1
    assert calls[0][1] == "test-topic"


@pytest.mark.asyncio
async def test_immediate_dlq_handler(scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch) -> None:
    p: UnifiedProducer = await scope.get(UnifiedProducer)
    calls: list[tuple[str | None, str, str, int]] = []

    async def _record_send_to_dlq(
        original_event: DomainEvent, original_topic: str, error: Exception, retry_count: int
    ) -> None:
        calls.append((original_event.event_id, original_topic, str(error), retry_count))

    monkeypatch.setattr(p, "send_to_dlq", _record_send_to_dlq)
    h = create_immediate_dlq_handler(p, logger=_test_logger)
    e = SagaStartedEvent(
        saga_id="s2",
        saga_name="n",
        execution_id="x",
        initial_event_id="i",
        metadata=EventMetadata(service_name="a", service_version="1"),
    )
    await h(RuntimeError("x"), e, "test-topic")
    assert calls and calls[0][1] == "test-topic"
    assert calls[0][3] == 0
