from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from aiokafka.errors import KafkaError

from app.core.metrics import ReplayMetrics
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


def _service(metrics: ReplayMetrics, producer: AsyncMock | None = None) -> tuple[EventReplayService, AsyncMock]:
    repo = AsyncMock(spec=ReplayRepository)
    repo.count_events.return_value = 0
    repo.fetch_events = MagicMock(side_effect=_no_batches)
    repo.delete_old_sessions.return_value = 0
    service = EventReplayService(
        repository=repo,
        producer=producer or AsyncMock(spec=UnifiedProducer),
        replay_metrics=metrics,
        logger=structlog.get_logger("test.replay_session_metrics"),
        sse_bus=AsyncMock(spec=SSERedisBus),
    )
    return service, repo


@pytest.mark.asyncio
async def test_cancelling_a_session_that_never_started_leaves_active_alone() -> None:
    metrics = MagicMock(spec=ReplayMetrics)
    service, _ = _service(metrics)
    created = await service.create_session_from_config(ReplayConfig(replay_type=ReplayType.EXECUTION))

    await service.cancel_session(created.session_id)

    metrics.decrement_active_replays.assert_not_called()
    metrics.record_status_change.assert_called_once_with(
        created.session_id, ReplayStatus.CREATED, ReplayStatus.CANCELLED
    )


@pytest.mark.asyncio
async def test_starting_with_nothing_to_replay_records_the_completion() -> None:
    metrics = MagicMock(spec=ReplayMetrics)
    service, _ = _service(metrics)
    created = await service.create_session_from_config(ReplayConfig(replay_type=ReplayType.EXECUTION))

    result = await service.start_session(created.session_id)

    assert result.status == ReplayStatus.COMPLETED
    metrics.record_status_change.assert_called_once_with(
        created.session_id, ReplayStatus.CREATED, ReplayStatus.COMPLETED
    )
    metrics.increment_active_replays.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_takes_removed_sessions_out_of_the_status_gauge() -> None:
    metrics = MagicMock(spec=ReplayMetrics)
    service, _ = _service(metrics)
    old = ReplaySessionState(
        session_id="old",
        config=ReplayConfig(replay_type=ReplayType.EXECUTION),
        status=ReplayStatus.COMPLETED,
        created_at=datetime.now(timezone.utc) - timedelta(hours=72),
    )
    service._sessions[old.session_id] = old

    result = await service.cleanup_old_sessions(older_than_hours=48)

    assert result.removed_sessions == 1
    metrics.update_sessions_by_status.assert_called_once_with(ReplayStatus.COMPLETED, -1)


def test_session_created_counts_towards_created_status() -> None:
    metrics = ReplayMetrics(MagicMock())
    metrics.replay_sessions_by_status = MagicMock()

    metrics.record_session_created(ReplayType.EXECUTION, "kafka")
    metrics.record_status_change("s1", ReplayStatus.CREATED, ReplayStatus.RUNNING)

    calls = [
        (c.args[0], c.kwargs["attributes"]["status"]) for c in metrics.replay_sessions_by_status.add.call_args_list
    ]
    assert calls == [(1, ReplayStatus.CREATED), (-1, ReplayStatus.CREATED), (1, ReplayStatus.RUNNING)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("produce_error", "success"),
    [(None, True), (KafkaError(), False), (TypeError("bug"), False)],
)
async def test_every_dispatch_outcome_counts_against_the_target(produce_error: Exception | None, success: bool) -> None:
    metrics = MagicMock(spec=ReplayMetrics)
    producer = AsyncMock(spec=UnifiedProducer)
    producer.produce.side_effect = produce_error
    service, _ = _service(metrics, producer)
    session = ReplaySessionState(session_id="s1", config=ReplayConfig(replay_type=ReplayType.EXECUTION))

    if isinstance(produce_error, TypeError):
        with pytest.raises(TypeError, match="bug"):
            await service._replay_event(session, make_execution_requested_event())
    else:
        assert await service._replay_event(session, make_execution_requested_event()) is success

    metrics.record_replay_by_target.assert_called_once_with(ReplayTarget.KAFKA, success=success)
