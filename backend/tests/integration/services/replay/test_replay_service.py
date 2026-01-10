import pytest
from dishka import AsyncContainer

from app.domain.enums.replay import ReplayTarget, ReplayType
from app.services.event_replay import ReplayConfig, ReplayFilter
from app.services.replay_service import ReplayService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_replay_service_create_and_list(scope: AsyncContainer) -> None:
    svc: ReplayService = await scope.get(ReplayService)

    cfg = ReplayConfig(
        replay_type=ReplayType.EXECUTION,
        target=ReplayTarget.TEST,
        filter=ReplayFilter(),
        max_events=1,
    )
    res = await svc.create_session_from_config(cfg)
    assert res.session_id and res.status.name in {"CREATED", "RUNNING", "COMPLETED"}

    # Sessions are tracked in memory; listing should work
    sessions = svc.list_sessions(limit=10)
    assert any(s.session_id == res.session_id for s in sessions)
