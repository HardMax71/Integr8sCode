from datetime import datetime, timezone, timedelta

import pytest

from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.domain.admin import ReplaySession, ReplayQuery
from app.domain.enums.replay import ReplayStatus
from app.domain.events.event_models import EventFields, EventFilter, EventStatistics, Event
from app.infrastructure.kafka.events.metadata import EventMetadata

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(db) -> AdminEventsRepository:  # type: ignore[valid-type]
    return AdminEventsRepository(db)


@pytest.mark.asyncio
async def test_browse_detail_delete_and_export(repo: AdminEventsRepository, db) -> None:  # type: ignore[valid-type]
    now = datetime.now(timezone.utc)
    await db.get_collection("events").insert_many([
        {EventFields.EVENT_ID: "e1", EventFields.EVENT_TYPE: "X", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="svc", service_version="1", correlation_id="c1").to_dict()},
        {EventFields.EVENT_ID: "e2", EventFields.EVENT_TYPE: "X", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="svc", service_version="1", correlation_id="c1").to_dict()},
    ])
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
    await db.get_collection("events").insert_many([
        {EventFields.EVENT_ID: "e10", EventFields.EVENT_TYPE: "step.completed", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="svc", service_version="1", user_id="u1").to_dict()},
    ])
    await db.get_collection("executions").insert_one({"created_at": now, "status": "completed", "resource_usage": {"execution_time_wall_seconds": 1.25}})
    stats = await repo.get_event_stats(hours=1)
    assert isinstance(stats, EventStatistics)
    ev = Event(event_id="a1", event_type="X", event_version="1.0", timestamp=now, metadata=EventMetadata(service_name="s", service_version="1"), payload={})
    assert await repo.archive_event(ev, deleted_by="admin") is True


@pytest.mark.asyncio
async def test_replay_session_flow_and_helpers(repo: AdminEventsRepository, db) -> None:  # type: ignore[valid-type]
    # create/get/update
    session = ReplaySession(session_id="s1", status=ReplayStatus.SCHEDULED, total_events=1, correlation_id="corr", created_at=datetime.now(timezone.utc) - timedelta(seconds=5), dry_run=False)
    sid = await repo.create_replay_session(session)
    assert sid == "s1"
    got = await repo.get_replay_session("s1")
    assert got and got.session_id == "s1"
    assert await repo.update_replay_session("s1", {"status": ReplayStatus.RUNNING}) is True
    detail = await repo.get_replay_status_with_progress("s1")
    assert detail and detail.session.session_id == "s1"
    assert await repo.count_events_for_replay({}) >= 0
    prev = await repo.get_replay_events_preview(event_ids=["e10"])  # from earlier insert
    assert isinstance(prev, dict)

