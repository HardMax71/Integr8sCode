import logging
from collections.abc import Callable
from typing import Any

import pytest
from app.events.core import UnifiedProducer, create_dlq_error_handler, create_immediate_dlq_handler
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.saga import SagaStartedEvent
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.dlq_handler")


@pytest.mark.asyncio
async def test_dlq_handler_with_retries(
    scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch, unique_id: Callable[[str], str]
) -> None:
    p: UnifiedProducer = await scope.get(UnifiedProducer)
    calls: list[tuple[str | None, str, str, int]] = []

    async def _record_send_to_dlq(original_event: Any, original_topic: str, error: Any, retry_count: int) -> None:
        calls.append((original_event.event_id, original_topic, str(error), retry_count))

    monkeypatch.setattr(p, "send_to_dlq", _record_send_to_dlq)
    uid = unique_id("")
    h = create_dlq_error_handler(p, original_topic=f"topic-{uid}", max_retries=2, logger=_test_logger)
    e = SagaStartedEvent(
        saga_id=f"saga-{uid}",
        saga_name="n",
        execution_id=f"exec-{uid}",
        initial_event_id=f"evt-{uid}",
        metadata=AvroEventMetadata(service_name="a", service_version="1"),
    )
    # Call 1 and 2 should not send to DLQ
    await h(RuntimeError("boom"), e)
    await h(RuntimeError("boom"), e)
    assert len(calls) == 0
    # 3rd call triggers DLQ
    await h(RuntimeError("boom"), e)
    assert len(calls) == 1
    assert calls[0][1] == f"topic-{uid}"


@pytest.mark.asyncio
async def test_immediate_dlq_handler(
    scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch, unique_id: Callable[[str], str]
) -> None:
    p: UnifiedProducer = await scope.get(UnifiedProducer)
    calls: list[tuple[str | None, str, str, int]] = []

    async def _record_send_to_dlq(original_event: Any, original_topic: str, error: Any, retry_count: int) -> None:
        calls.append((original_event.event_id, original_topic, str(error), retry_count))

    monkeypatch.setattr(p, "send_to_dlq", _record_send_to_dlq)
    uid = unique_id("")
    h = create_immediate_dlq_handler(p, original_topic=f"topic-{uid}", logger=_test_logger)
    e = SagaStartedEvent(
        saga_id=f"saga-{uid}",
        saga_name="n",
        execution_id=f"exec-{uid}",
        initial_event_id=f"evt-{uid}",
        metadata=AvroEventMetadata(service_name="a", service_version="1"),
    )
    await h(RuntimeError("x"), e)
    assert calls and calls[0][3] == 0
