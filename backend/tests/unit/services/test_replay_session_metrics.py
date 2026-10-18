from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from aiokafka.errors import KafkaError
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.db import ReplayRepository
from app.domain.enums import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayConfig, ReplaySessionState
from app.events import UnifiedProducer
from app.services.event_replay import EventReplayService
from app.services.sse import SSERedisBus
from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit


async def _no_batches(*_: Any, **__: Any) -> AsyncIterator[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    for batch in batches:
        yield batch


def _service(tracer: trace.Tracer, producer: AsyncMock | None = None) -> EventReplayService:
    repo = AsyncMock(spec=ReplayRepository)
    repo.count_events.return_value = 0
    repo.fetch_events = MagicMock(side_effect=_no_batches)
    repo.delete_old_sessions.return_value = 0
    return EventReplayService(
        repository=repo,
        producer=producer or AsyncMock(spec=UnifiedProducer),
        tracer=tracer,
        logger=structlog.get_logger("test.replay_session_metrics"),
        sse_bus=AsyncMock(spec=SSERedisBus),
    )


def _spans(exporter: InMemorySpanExporter) -> list[tuple[str, dict[str, Any]]]:
    return [(span.name, dict(span.attributes or {})) for span in exporter.get_finished_spans()]


async def test_cancelling_a_session_that_never_started_reports_one_status_change(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    service = _service(tracer)
    created = await service.create_session_from_config(ReplayConfig(replay_type=ReplayType.EXECUTION))

    await service.cancel_session(created.session_id)

    assert _spans(span_exporter) == [
        ("replay.session_created", {"replay.type": "execution", "replay.target": "kafka"}),
        ("replay.status_change", {"replay.from_status": "created", "replay.to_status": "cancelled"}),
    ]


async def test_starting_with_nothing_to_replay_reports_the_completion(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    service = _service(tracer)
    created = await service.create_session_from_config(ReplayConfig(replay_type=ReplayType.EXECUTION))

    result = await service.start_session(created.session_id)

    assert result.status == ReplayStatus.COMPLETED
    assert [name for name, _ in _spans(span_exporter)] == ["replay.session_created", "replay.status_change"]
    assert _spans(span_exporter)[1][1] == {"replay.from_status": "created", "replay.to_status": "completed"}


async def test_report_counts_held_sessions_by_status_and_events_still_to_send(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    service = _service(tracer)
    created = await service.create_session_from_config(ReplayConfig(replay_type=ReplayType.EXECUTION))
    old = ReplaySessionState(
        session_id="old",
        config=ReplayConfig(replay_type=ReplayType.EXECUTION),
        status=ReplayStatus.COMPLETED,
        created_at=datetime.now(timezone.utc) - timedelta(hours=72),
    )
    service._sessions[old.session_id] = old
    service._event_buffers[created.session_id] = [make_execution_requested_event() for _ in range(5)]
    service._buffer_indices[created.session_id] = 2
    await service.cleanup_old_sessions(older_than_hours=48)
    span_exporter.clear()

    await service.report_sessions()

    *sessions, (report_name, report) = _spans(span_exporter)
    assert (report_name, report) == ("replay.report", {"replay.queued_events": 3})
    counts = {attributes["replay.status"]: attributes["replay.sessions"] for _, attributes in sessions}
    assert counts == {status: 1 if status == ReplayStatus.CREATED else 0 for status in ReplayStatus}


@pytest.mark.parametrize(
    ("produce_error", "success"),
    [(None, True), (KafkaError(), False), (TypeError("bug"), False)],
)
async def test_every_dispatch_outcome_counts_against_the_target(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter, produce_error: Exception | None, success: bool
) -> None:
    producer = AsyncMock(spec=UnifiedProducer)
    producer.produce.side_effect = produce_error
    service = _service(tracer, producer)
    session = ReplaySessionState(session_id="s1", config=ReplayConfig(replay_type=ReplayType.EXECUTION))

    if isinstance(produce_error, TypeError):
        with pytest.raises(TypeError, match="bug"):
            await service._replay_event(session, make_execution_requested_event())
    else:
        assert await service._replay_event(session, make_execution_requested_event()) is success

    assert _spans(span_exporter) == [("replay.target", {"replay.target": "kafka", "replay.target_success": success})]


async def test_dispatch_reports_each_event_and_the_completed_session(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    service = _service(tracer)
    config = ReplayConfig(replay_type=ReplayType.EXECUTION, target=ReplayTarget.TEST, speed_multiplier=2.0)
    session = ReplaySessionState(
        session_id="s1",
        config=config,
        status=ReplayStatus.RUNNING,
        started_at=datetime.now(timezone.utc) - timedelta(seconds=4),
    )
    first, second = make_execution_requested_event(), make_execution_requested_event()
    second.timestamp = first.timestamp + timedelta(milliseconds=40)
    service._sessions[session.session_id] = session
    service._event_buffers[session.session_id] = [first, second]

    await service._dispatch_events(session)

    spans = _spans(span_exporter)
    events = [attributes for name, attributes in spans if name == "replay.event"]
    assert [(e["replay.result"], e.get("replay.delay_seconds")) for e in events] == [
        ("replayed", pytest.approx(0.02)),
        ("replayed", None),
    ]
    [completed] = [attributes for name, attributes in spans if name == "replay.session_completed"]
    assert completed["replay.duration_seconds"] >= 4
    assert completed["replay.throughput"] == pytest.approx(2 / completed["replay.duration_seconds"])
    assert spans[-1] == ("replay.status_change", {"replay.from_status": "running", "replay.to_status": "completed"})
