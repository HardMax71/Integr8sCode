from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.core.metrics import ReplayMetrics
from app.db import ReplayRepository
from app.domain.enums import ReplayStatus, ReplayType
from app.domain.replay import ReplayConfig, ReplaySessionState
from app.events import UnifiedProducer
from app.services.event_replay import EventReplayService
from app.services.sse import SSERedisBus

pytestmark = pytest.mark.unit


async def _no_batches(*_: Any, **__: Any) -> AsyncIterator[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    for batch in batches:
        yield batch


def _service(metrics: ReplayMetrics) -> tuple[EventReplayService, AsyncMock]:
    repo = AsyncMock(spec=ReplayRepository)
    repo.count_events.return_value = 0
    repo.fetch_events = MagicMock(side_effect=_no_batches)
    repo.delete_old_sessions.return_value = 0
    service = EventReplayService(
        repository=repo,
        producer=AsyncMock(spec=UnifiedProducer),
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
