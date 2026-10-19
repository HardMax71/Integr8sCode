from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.domain.enums import EventType
from app.domain.events import BaseEvent
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus, KeyStrategy
from app.services.idempotency import IdempotencyConfig, IdempotencyManager, RedisIdempotencyRepository

pytestmark = pytest.mark.unit

# Test logger
_test_logger = structlog.get_logger("test.idempotency_manager")


def test_manager_generate_key_variants() -> None:
    repo = MagicMock()
    mgr = IdempotencyManager(IdempotencyConfig(), repo, _test_logger, tracer=trace.NoOpTracer())
    ev = MagicMock(spec=BaseEvent)
    ev.event_type = "t"
    ev.event_id = "e"
    ev.model_dump.return_value = {"event_id": "e", "event_type": "t"}

    assert mgr._generate_key(ev, KeyStrategy.EVENT_BASED) == "idempotency:t:e"
    ch = mgr._generate_key(ev, KeyStrategy.CONTENT_HASH)
    assert ch.startswith("idempotency:") and len(ch.split(":")[-1]) == 64
    assert mgr._generate_key(ev, KeyStrategy.CUSTOM, custom_key="k") == "idempotency:t:k"
    with pytest.raises(ValueError):
        mgr._generate_key(ev, KeyStrategy.CUSTOM)  # CUSTOM requires custom_key


def _event() -> MagicMock:
    ev = MagicMock(spec=BaseEvent)
    ev.event_type = EventType.CREATE_POD_COMMAND
    ev.event_id = "evt-1"
    return ev


def _manager(repo: AsyncMock, tracer: trace.Tracer) -> IdempotencyManager:
    return IdempotencyManager(IdempotencyConfig(), repo, _test_logger, tracer=tracer)


def _record(status: IdempotencyStatus) -> IdempotencyRecord:
    return IdempotencyRecord(
        key="idempotency:create_pod_command:evt-1",
        status=status,
        event_type=EventType.CREATE_POD_COMMAND,
        event_id="evt-1",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        ttl_seconds=3600,
    )


@pytest.mark.parametrize(
    ("method", "kwargs", "expected_status"),
    [
        ("mark_completed", {}, IdempotencyStatus.COMPLETED),
        ("mark_failed", {"error": "boom"}, IdempotencyStatus.FAILED),
        ("mark_completed_with_json", {"cached_json": "{}"}, IdempotencyStatus.COMPLETED),
    ],
)
async def test_marking_records_processing_duration(
    tracer: trace.Tracer,
    span_exporter: InMemorySpanExporter,
    method: str,
    kwargs: dict[str, str],
    expected_status: IdempotencyStatus,
) -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = _record(IdempotencyStatus.PROCESSING)
    repo.update_record.return_value = 1

    assert await getattr(_manager(repo, tracer), method)(_event(), **kwargs) is True

    [span] = span_exporter.get_finished_spans()
    assert span.name == "idempotency.processed"
    assert span.attributes is not None
    seconds = span.attributes["idempotency.processing_seconds"]
    assert isinstance(seconds, float)
    assert seconds >= 2.0
    assert (span.attributes["idempotency.event_type"], span.attributes["idempotency.status"]) == (
        EventType.CREATE_POD_COMMAND,
        expected_status,
    )


async def test_marking_missing_key_records_nothing(tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = None

    assert await _manager(repo, tracer).mark_completed(_event()) is False

    assert span_exporter.get_finished_spans() == ()
    repo.update_record.assert_not_called()


async def test_check_and_reserve_of_a_new_key_reports_a_miss(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = None

    result = await _manager(repo, tracer).check_and_reserve(_event())

    assert result.is_duplicate is False
    assert result.status == IdempotencyStatus.PROCESSING
    repo.insert_processing.assert_awaited_once()
    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == (
        "idempotency.check",
        {
            "idempotency.event_type": EventType.CREATE_POD_COMMAND,
            "idempotency.operation": "check_and_reserve",
            "idempotency.result": "miss",
        },
    )


async def test_check_and_reserve_of_a_done_key_reports_a_hit_and_a_blocked_duplicate(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.find_by_key.return_value = _record(IdempotencyStatus.COMPLETED)

    result = await _manager(repo, tracer).check_and_reserve(_event())

    assert result.is_duplicate is True
    blocked, check = span_exporter.get_finished_spans()
    assert (blocked.name, blocked.attributes) == (
        "idempotency.duplicate_blocked",
        {"idempotency.event_type": EventType.CREATE_POD_COMMAND},
    )
    assert check.attributes is not None
    assert (check.name, check.attributes["idempotency.result"]) == ("idempotency.check", "hit")


async def test_report_active_keys_puts_the_redis_count_on_a_span(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    repo = AsyncMock(spec=RedisIdempotencyRepository)
    repo.count_keys.return_value = 3

    await _manager(repo, tracer).report_active_keys()

    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == ("idempotency.keys", {"idempotency.active_keys": 3})
