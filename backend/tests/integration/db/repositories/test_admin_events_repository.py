from datetime import datetime, timedelta, timezone

import pytest
from app.db.docs.replay import ReplayConfig, ReplayFilter
from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.domain.admin import ReplayQuery
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.events.event_models import Event, EventFilter, EventStatistics
from app.domain.replay.models import ReplaySessionState
from app.infrastructure.kafka.events.metadata import AvroEventMetadata

pytestmark = pytest.mark.integration


@pytest.fixture()
async def repo(scope) -> AdminEventsRepository:  # type: ignore[valid-type]
    return await scope.get(AdminEventsRepository)


@pytest.mark.asyncio
async def test_browse_detail_delete_and_export(repo: AdminEventsRepository, db) -> None:  # type: ignore[valid-type]
    now = datetime.now(timezone.utc)
    await db.get_collection("events").insert_many(
        [
            {
                "event_id": "e1",
                "event_type": "X",
                "timestamp": now,
                "metadata": AvroEventMetadata(
                    service_name="svc", service_version="1", correlation_id="c1"
                ).model_dump(),
            },
            {
                "event_id": "e2",
                "event_type": "X",
                "timestamp": now,
                "metadata": AvroEventMetadata(
                    service_name="svc", service_version="1", correlation_id="c1"
                ).model_dump(),
            },
        ]
    )
    res = await repo.browse_events(EventFilter())
    assert res.total >= 2
    detail = await repo.get_event_detail("e1")
    assert detail and detail.event.event_id == "e1"
    assert await repo.delete_event("e2") is True
    rows = await repo.export_events_csv(EventFilter())
    assert isinstance(rows, list) and len(rows) >= 1


@pytest.mark.asyncio
async def test_event_stats_and_archive(repo: AdminEventsRepository, db) -> None:  # type: ignore[valid-type]
    now = datetime.now(timezone.utc)
    await db.get_collection("events").insert_many(
        [
            {
                "event_id": "e10",
                "event_type": "step.completed",
                "timestamp": now,
                "metadata": AvroEventMetadata(service_name="svc", service_version="1", user_id="u1").model_dump(),
            },
        ]
    )
    await db.get_collection("executions").insert_one(
        {"created_at": now, "status": "completed", "resource_usage": {"execution_time_wall_seconds": 1.25}}
    )
    stats = await repo.get_event_stats(hours=1)
    assert isinstance(stats, EventStatistics)
    ev = Event(
        event_id="a1",
        event_type="X",
        event_version="1.0",
        timestamp=now,
        metadata=AvroEventMetadata(service_name="s", service_version="1"),
        payload={},
    )
    assert await repo.archive_event(ev, deleted_by="admin") is True


@pytest.mark.asyncio
async def test_replay_session_flow_and_helpers(repo: AdminEventsRepository, db) -> None:  # type: ignore[valid-type]
    # create/get/update
    config = ReplayConfig(
        replay_type=ReplayType.QUERY,
        target=ReplayTarget.TEST,
        filter=ReplayFilter(),
    )
    session = ReplaySessionState(
        session_id="s1",
        config=config,
        status=ReplayStatus.SCHEDULED,
        total_events=1,
        correlation_id="corr",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        dry_run=False,
    )
    sid = await repo.create_replay_session(session)
    assert sid == "s1"
    got = await repo.get_replay_session("s1")
    assert got and got.session_id == "s1"
    session_update = ReplaySessionUpdate(status=ReplayStatus.RUNNING)
    assert await repo.update_replay_session("s1", session_update) is True
    detail = await repo.get_replay_status_with_progress("s1")
    assert detail and detail.session.session_id == "s1"
    assert await repo.count_events_for_replay(ReplayQuery()) >= 0
    prev = await repo.get_replay_events_preview(event_ids=["e10"])  # from earlier insert
    assert isinstance(prev, dict)
