from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import structlog
from aiokafka.errors import KafkaError
from faststream.kafka import KafkaBroker
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.db import DLQRepository
from app.db.docs import DLQMessageDocument
from app.dlq.manager import DLQManager
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.settings import Settings

pytestmark = pytest.mark.unit


@pytest.fixture
def broker() -> AsyncMock:
    return AsyncMock(spec=KafkaBroker)


@pytest.fixture
def repository() -> AsyncMock:
    return AsyncMock(spec=DLQRepository)


@pytest.fixture
def manager(test_settings: Settings, broker: AsyncMock, repository: AsyncMock, tracer: trace.Tracer) -> DLQManager:
    return DLQManager(test_settings, broker, structlog.get_logger("test"), tracer, repository)


def _message(retry_count: int = 0, failed_at: datetime | None = None) -> DLQMessageDocument:
    event = UserRegisteredEvent(
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(service_name="auth-service", service_version="1", user_id="u1"),
    )
    return DLQMessageDocument(
        event=event,
        original_topic="user_registered",
        consumer_group="group-a",
        retry_count=retry_count,
        failed_at=failed_at or datetime.now(timezone.utc),
    )


async def test_stored_message_reports_its_age(manager: DLQManager, span_exporter: InMemorySpanExporter) -> None:
    await manager.handle_message(_message(failed_at=datetime.now(timezone.utc) - timedelta(seconds=30)))

    [span] = span_exporter.get_finished_spans()
    assert span.name == "dlq.handle"
    assert span.attributes is not None
    age = span.attributes["dlq.message_age_seconds"]
    assert isinstance(age, float)
    assert 30 <= age < 40
    assert {k: v for k, v in span.attributes.items() if k != "dlq.message_age_seconds"} == {
        "dlq.operation": "handle",
        "dlq.original_topic": "user_registered",
        "dlq.event_type": "user_registered",
        "dlq.outcome": "stored",
    }


async def test_filtered_message_is_not_stored(
    manager: DLQManager, repository: AsyncMock, span_exporter: InMemorySpanExporter
) -> None:
    await manager.handle_message(_message(failed_at=datetime.now(timezone.utc) - timedelta(days=8)))

    repository.save_message.assert_not_awaited()
    [span] = span_exporter.get_finished_spans()
    assert span.attributes is not None
    assert (span.name, span.attributes["dlq.outcome"]) == ("dlq.handle", "filtered")


async def test_message_out_of_retries_is_discarded_inside_the_handle_span(
    manager: DLQManager, span_exporter: InMemorySpanExporter
) -> None:
    await manager.handle_message(_message(retry_count=4))

    discard, handle = span_exporter.get_finished_spans()
    assert discard.parent is not None
    assert discard.parent.span_id == handle.context.span_id
    assert (discard.name, discard.attributes) == (
        "dlq.discard",
        {
            "dlq.operation": "discard",
            "dlq.original_topic": "user_registered",
            "dlq.event_type": "user_registered",
            "dlq.discard_reason": "max_retries_exceeded",
        },
    )


async def test_retry_reports_success(manager: DLQManager, span_exporter: InMemorySpanExporter) -> None:
    await manager.retry_message(_message(retry_count=1))

    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == (
        "dlq.retry",
        {
            "dlq.operation": "retry",
            "dlq.original_topic": "user_registered",
            "dlq.event_type": "user_registered",
            "dlq.retry_result": "success",
        },
    )


async def test_failed_retry_reports_the_error_type(
    manager: DLQManager, broker: AsyncMock, span_exporter: InMemorySpanExporter
) -> None:
    broker.publish.side_effect = KafkaError("broker down")

    with pytest.raises(KafkaError):
        await manager.retry_message(_message(retry_count=1))

    [span] = span_exporter.get_finished_spans()
    assert span.attributes is not None
    assert (span.name, span.attributes["dlq.retry_result"], span.attributes["dlq.error_type"]) == (
        "dlq.retry",
        "failed",
        "KafkaError",
    )


async def test_monitoring_cycle_reports_each_topic_size(
    manager: DLQManager, repository: AsyncMock, span_exporter: InMemorySpanExporter
) -> None:
    repository.find_due_retries.return_value = []
    repository.get_queue_sizes_by_topic.return_value = {"execution_requested": 3, "user_registered": 1}

    await manager.process_monitoring_cycle()

    *sizes, cycle = span_exporter.get_finished_spans()
    assert cycle.name == "dlq.monitoring_cycle"
    assert [(s.name, s.attributes) for s in sizes] == [
        ("dlq.queue_size", {"dlq.original_topic": "execution_requested", "dlq.size": 3}),
        ("dlq.queue_size", {"dlq.original_topic": "user_registered", "dlq.size": 1}),
    ]
    assert all(s.parent is not None and s.parent.span_id == cycle.context.span_id for s in sizes)
