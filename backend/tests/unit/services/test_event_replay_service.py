from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from aiokafka.errors import KafkaError
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.db import ReplayRepository
from app.db.docs import ReplaySessionDocument
from app.domain.enums import ReplayStatus
from app.domain.replay import ReplayConfig, ReplayFilter
from app.events import UnifiedProducer
from app.services.event_replay import EventReplayService
from app.services.sse import SSERedisBus
from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit

_FIRST = make_execution_requested_event(execution_id="e1").model_dump()
_SECOND = make_execution_requested_event(execution_id="e2").model_dump()


async def _batches(*batches: list[dict[str, Any]]) -> AsyncIterator[list[dict[str, Any]]]:
    for batch in batches:
        yield batch


def _session(max_events: int = 10) -> ReplaySessionDocument:
    return ReplaySessionDocument(
        config=ReplayConfig(filter=ReplayFilter(aggregate_id="agg"), max_events=max_events), total_events=2
    )


def _service(
    tracer: trace.Tracer, repo: AsyncMock, producer: AsyncMock, sse_bus: AsyncMock | None = None
) -> EventReplayService:
    return EventReplayService(
        repo, producer, sse_bus or AsyncMock(spec=SSERedisBus), structlog.get_logger("test.replay"), tracer
    )


def _repo(session: ReplaySessionDocument | None, *docs: dict[str, Any]) -> AsyncMock:
    repo = AsyncMock(spec=ReplayRepository)
    repo.get_oldest_scheduled_session.return_value = session
    repo.fetch_events = MagicMock(return_value=_batches(list(docs)))
    return repo


async def test_nothing_happens_without_a_scheduled_session(tracer: trace.Tracer) -> None:
    repo = _repo(None)
    producer = AsyncMock(spec=UnifiedProducer)

    await _service(tracer, repo, producer).run_next_session()

    repo.save_session.assert_not_awaited()
    producer.produce.assert_not_awaited()


async def test_replays_every_event_in_order_and_completes(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    session = _session()
    repo = _repo(session, _FIRST, _SECOND)
    producer = AsyncMock(spec=UnifiedProducer)
    sse_bus = AsyncMock(spec=SSERedisBus)
    before = datetime.now(timezone.utc)

    await _service(tracer, repo, producer, sse_bus).run_next_session()

    sent = [c.kwargs["event_to_produce"] for c in producer.produce.await_args_list]
    assert [e.event_id for e in sent] == [_FIRST["event_id"], _SECOND["event_id"]]
    assert all(e.timestamp >= before for e in sent)
    assert (session.status, session.replayed_events, session.failed_events) == (ReplayStatus.COMPLETED, 2, 0)
    assert session.started_at is not None and session.completed_at is not None
    assert sse_bus.publish_replay_status.await_args.args[1].status == ReplayStatus.COMPLETED
    names = [span.name for span in span_exporter.get_finished_spans()]
    assert names == [
        "replay.status_change",
        "replay.batch",
        "replay.event",
        "replay.event",
        "replay.status_change",
        "replay.session_completed",
    ]


@pytest.mark.parametrize(
    ("first", "produce_errors", "error_type"),
    [
        (_FIRST, [KafkaError("broker down"), None], "KafkaError"),
        (_FIRST | {"event_type": "saga_started"}, [None], "ValidationError"),
    ],
)
async def test_an_event_that_fails_counts_and_the_replay_goes_on(
    tracer: trace.Tracer, first: dict[str, Any], produce_errors: list[Exception | None], error_type: str
) -> None:
    session = _session()
    producer = AsyncMock(spec=UnifiedProducer)
    producer.produce.side_effect = produce_errors

    await _service(tracer, _repo(session, first, _SECOND), producer).run_next_session()

    assert (session.status, session.replayed_events, session.failed_events) == (ReplayStatus.COMPLETED, 1, 1)
    [error] = session.errors
    assert (error.event_id, error.error_type) == (_FIRST["event_id"], error_type)


async def test_max_events_caps_the_replay(tracer: trace.Tracer) -> None:
    session = _session(max_events=1)
    producer = AsyncMock(spec=UnifiedProducer)

    await _service(tracer, _repo(session, _FIRST, _SECOND), producer).run_next_session()

    assert producer.produce.await_count == 1
    assert (session.status, session.replayed_events) == (ReplayStatus.COMPLETED, 1)


async def test_an_unexpected_error_fails_the_session_and_propagates(tracer: trace.Tracer) -> None:
    session = _session()
    producer = AsyncMock(spec=UnifiedProducer)
    producer.produce.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _service(tracer, _repo(session, _FIRST), producer).run_next_session()

    assert session.status == ReplayStatus.FAILED
    assert (session.errors[-1].error, session.errors[-1].error_type) == ("boom", "RuntimeError")


async def test_a_restart_fails_the_running_sessions(tracer: trace.Tracer) -> None:
    session = _session()
    session.status = ReplayStatus.RUNNING
    repo = _repo(None)
    repo.get_running_sessions.return_value = [session]

    await _service(tracer, repo, AsyncMock(spec=UnifiedProducer)).fail_interrupted_sessions()

    assert session.status == ReplayStatus.FAILED
    assert session.errors[-1].error == "The worker restarted during the replay"
    repo.save_session.assert_awaited_once_with(session)


async def test_report_sessions_reports_every_status(tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
    repo = _repo(None)
    repo.count_by_status.return_value = {ReplayStatus.RUNNING: 2}

    await _service(tracer, repo, AsyncMock(spec=UnifiedProducer)).report_sessions()

    reported = {
        span.attributes["replay.status"]: span.attributes["replay.sessions"]
        for span in span_exporter.get_finished_spans()
        if span.attributes
    }
    assert reported == {status: 2 if status == ReplayStatus.RUNNING else 0 for status in ReplayStatus}
