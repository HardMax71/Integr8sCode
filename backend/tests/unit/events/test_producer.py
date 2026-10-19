from unittest.mock import AsyncMock

import pytest
from aiokafka.errors import KafkaError
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.db import EventRepository
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.events import UnifiedProducer
from app.events.core.transport import KafkaEventTransport

pytestmark = pytest.mark.unit


def _event() -> UserRegisteredEvent:
    return UserRegisteredEvent(
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(service_name="test", service_version="1", user_id="u1"),
    )


def _producer(tracer: trace.Tracer) -> tuple[UnifiedProducer, AsyncMock, AsyncMock]:
    repo = AsyncMock(spec=EventRepository)
    transport = AsyncMock(spec=KafkaEventTransport)
    return UnifiedProducer(repo, transport, tracer), repo, transport


async def test_produce_stores_publishes_and_reports_a_clean_span(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    producer, repo, transport = _producer(tracer)
    event = _event()

    await producer.produce(event_to_produce=event, key="u1")

    repo.store_event.assert_awaited_once_with(event)
    transport.publish.assert_awaited_once_with(event, event.event_type, "u1")
    [span] = span_exporter.get_finished_spans()
    assert span.attributes is not None
    assert (span.name, span.attributes["event.type"], span.status.status_code) == (
        "publish_event",
        event.event_type,
        StatusCode.UNSET,
    )


async def test_failed_publish_is_marked_and_its_span_is_an_error(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    producer, repo, transport = _producer(tracer)
    transport.publish.side_effect = KafkaError("broker down")
    event = _event()

    with pytest.raises(KafkaError):
        await producer.produce(event_to_produce=event, key="u1")

    repo.mark_publish_failed.assert_awaited_once_with(event.event_id)
    [span] = span_exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
