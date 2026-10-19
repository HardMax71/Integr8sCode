import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from opentelemetry import trace

from app.db import ReplayRepository
from app.domain.enums import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayConfig
from app.events import UnifiedProducer
from app.services.event_replay import EventReplayService
from app.services.sse import SSERedisBus
from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit

_DOCS = [make_execution_requested_event(execution_id=f"e{n}").model_dump() for n in range(25)]


async def _batches(*_: Any, batch_size: int, **__: Any) -> AsyncIterator[list[dict[str, Any]]]:
    for start in range(0, len(_DOCS), batch_size):
        yield _DOCS[start : start + batch_size]


@pytest.mark.parametrize("speed_multiplier", [100.0, 99.0])
async def test_a_replay_without_waits_sends_every_event(speed_multiplier: float) -> None:
    repo = AsyncMock(spec=ReplayRepository)
    repo.count_events.return_value = len(_DOCS)
    repo.fetch_events = MagicMock(side_effect=_batches)
    service = EventReplayService(
        repository=repo,
        producer=AsyncMock(spec=UnifiedProducer),
        tracer=trace.NoOpTracer(),
        logger=structlog.get_logger("test.replay_dispatch"),
        sse_bus=AsyncMock(spec=SSERedisBus),
    )
    config = ReplayConfig(
        replay_type=ReplayType.QUERY, target=ReplayTarget.TEST, speed_multiplier=speed_multiplier, batch_size=10
    )
    created = await service.create_session_from_config(config)

    await service.start_session(created.session_id)
    async with asyncio.timeout(5):
        while not service.get_session(created.session_id).status.is_terminal:
            await asyncio.sleep(0.01)

    session = service.get_session(created.session_id)
    assert (session.status, session.replayed_events, session.failed_events) == (ReplayStatus.COMPLETED, 25, 0)
