import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

from app.db.repositories.admin.admin_events_repository import AdminEventsRepository
from app.domain.events.event_models import EventFields, EventFilter, EventStatistics
from app.infrastructure.kafka.events.metadata import EventMetadata


pytestmark = pytest.mark.unit


# mock_db fixture now provided by main conftest.py


@pytest.fixture()
def repo(mock_db) -> AdminEventsRepository:
    return AdminEventsRepository(mock_db)


@pytest.mark.asyncio
async def test_browse_and_detail_and_delete(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # browse
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs

    now = datetime.now(timezone.utc)
    ev_doc = {
        EventFields.EVENT_ID: "e1",
        EventFields.EVENT_TYPE: "X",
        EventFields.TIMESTAMP: now,
        EventFields.METADATA: EventMetadata(service_name="svc", service_version="1").to_dict(),
    }
    mock_db.events.count_documents = AsyncMock(return_value=1)
    mock_db.events.find.return_value = Cursor([ev_doc])
    res = await repo.browse_events(EventFilter())
    assert res.total == 1 and len(res.events) == 1

    # detail with related
    mock_db.events.find_one = AsyncMock(return_value=ev_doc)
    mock_db.events.find.return_value = Cursor([
        ev_doc | {EventFields.EVENT_ID: "e2"},
    ])
    detail = await repo.get_event_detail("e1")
    assert detail and detail.event.event_id == "e1" and len(detail.related_events) >= 0

    mock_db.events.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    assert await repo.delete_event("e1") is True


@pytest.mark.asyncio
async def test_archive_event(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    from app.domain.events.event_models import Event
    ev = Event(
        event_id="e3",
        event_type="X",
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata=EventMetadata(service_name="s", service_version="1"),
        payload={},
    )
    archived_coll = mock_db.get_collection("archived_events")
    archived_coll.insert_one = AsyncMock()
    assert await repo.archive_event(ev, deleted_by="admin") is True


@pytest.mark.asyncio
async def test_get_event_stats_and_export(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # stats aggregates
    now = datetime.now(timezone.utc)
    overview_docs = [{"total_events": 10, "event_type_count": 2, "unique_user_count": 2, "service_count": 1}]
    type_docs = [{"_id": "X", "count": 5}]
    hour_docs = [{"_id": now.strftime("%Y-%m-%d %H:00"), "count": 3}]
    user_docs = [{"_id": "u1", "count": 4}]

    agg_overview = AsyncMock(); agg_overview.to_list = AsyncMock(return_value=overview_docs)
    agg_types = AsyncMock(); agg_types.to_list = AsyncMock(return_value=type_docs)

    class AggIter:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    # event_collection.aggregate called multiple times in order
    def agg_side_effect(_pipeline):
        if not hasattr(agg_side_effect, "calls"):
            agg_side_effect.calls = 0  # type: ignore[attr-defined]
        agg_side_effect.calls += 1  # type: ignore[attr-defined]
        if agg_side_effect.calls == 1:
            return agg_overview
        elif agg_side_effect.calls == 2:
            # For type aggregation
            type_agg = AsyncMock()
            type_agg.to_list = AsyncMock(return_value=type_docs)
            return type_agg
        elif agg_side_effect.calls == 3:
            return AggIter(hour_docs)
        else:
            return AggIter(user_docs)

    mock_db.events.aggregate = MagicMock(side_effect=agg_side_effect)
    # executions avg time aggregate
    exec_agg = AsyncMock(); exec_agg.to_list = AsyncMock(return_value=[{"avg_duration": 1.23}])
    executions_coll = mock_db.get_collection("executions")
    executions_coll.aggregate = MagicMock(return_value=exec_agg)

    stats = await repo.get_event_stats(hours=1)
    assert isinstance(stats, EventStatistics) and stats.total_events == 10 and stats.events_by_type.get("X") == 5

    # export
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs

    mock_db.events.find.return_value = Cursor([{
        EventFields.EVENT_ID: "e1",
        EventFields.EVENT_TYPE: "X",
        EventFields.TIMESTAMP: now,
        EventFields.METADATA: EventMetadata(service_name="svc", service_version="1").to_dict(),
    }])
    rows = await repo.export_events_csv(EventFilter())
    assert len(rows) == 1 and rows[0].event_id == "e1"


@pytest.mark.asyncio
async def test_replay_session_flows(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # create/get/update
    from app.domain.admin.replay_models import ReplaySession, ReplaySessionStatus

    session = ReplaySession(
        session_id="s1",
        status=ReplaySessionStatus.SCHEDULED,
        total_events=10,
        correlation_id="corr",
        created_at=datetime.now(timezone.utc) - timedelta(seconds=5),
        dry_run=False,
    )
    mock_db.replay_sessions.insert_one = AsyncMock()
    sid = await repo.create_replay_session(session)
    assert sid == "s1"

    # get
    from app.infrastructure.mappers.replay_mapper import ReplaySessionMapper
    mock_db.replay_sessions.find_one = AsyncMock(return_value=ReplaySessionMapper.to_dict(session))
    got = await repo.get_replay_session("s1")
    assert got and got.session_id == "s1"

    # update partial
    mock_db.replay_sessions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    ok = await repo.update_replay_session("s1", {"status": ReplaySessionStatus.RUNNING})
    assert ok is True

    # status with progress: should update to running if it's been scheduled for >2s
    session_dict = ReplaySessionMapper.to_dict(session)
    # Make scheduled a bit older to trigger update logic
    session_dict['created_at'] = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    mock_db.replay_sessions.find_one_and_update = AsyncMock(return_value=session_dict)
    detail = await repo.get_replay_status_with_progress("s1")
    assert detail and detail.session.session_id == "s1"

    # count and preview for replay
    mock_db.events.count_documents = AsyncMock(return_value=3)
    class Cursor:  # simple to_list for previews
        def __init__(self, docs):
            self._docs = docs
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs
    mock_db.events.find = MagicMock(return_value=Cursor([{
        EventFields.EVENT_ID: "e1",
        EventFields.EVENT_TYPE: "X",
        EventFields.TIMESTAMP: datetime.now(timezone.utc),
        EventFields.METADATA: EventMetadata(service_name="svc", service_version="1").to_dict(),
    }]))
    from app.domain.admin.replay_models import ReplayQuery
    q = repo.build_replay_query(ReplayQuery(event_ids=["e1"]))
    assert EventFields.EVENT_ID in q

    data = await repo.prepare_replay_session(q, dry_run=True, replay_correlation_id="rc")
    assert data.total_events == 3 and data.dry_run is True


@pytest.mark.asyncio
async def test_prepare_replay_session_validations(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # 0 events -> ValueError
    mock_db.events.count_documents = AsyncMock(return_value=0)
    with pytest.raises(ValueError):
        await repo.prepare_replay_session({}, dry_run=False, replay_correlation_id="rc")

    # too many events and not dry_run -> ValueError
    mock_db.events.count_documents = AsyncMock(return_value=5000)
    with pytest.raises(ValueError):
        await repo.prepare_replay_session({}, dry_run=False, replay_correlation_id="rc", max_events=1000)

    # get_replay_events_preview
    mock_db.event_store.count_documents = AsyncMock(return_value=1)
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs
    mock_db.event_store.find = MagicMock(return_value=Cursor([{"x": 1}]))
    prev = await repo.get_replay_events_preview(event_ids=["e1"]) 
    assert prev["total"] == 1


@pytest.mark.asyncio
async def test_get_event_detail_not_found(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    mock_db.events.find_one = AsyncMock(return_value=None)
    assert await repo.get_event_detail("missing") is None


@pytest.mark.asyncio
async def test_get_replay_status_with_progress_running(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    from app.domain.admin.replay_models import ReplaySession, ReplaySessionStatus
    # session running with started_at
    session = ReplaySession(
        session_id="s2",
        status=ReplaySessionStatus.RUNNING,
        total_events=20,
        correlation_id="c",
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc) - timedelta(seconds=3),
    )
    from app.infrastructure.mappers.replay_mapper import ReplaySessionMapper
    mock_db.replay_sessions.find_one = AsyncMock(return_value=ReplaySessionMapper.to_dict(session))

    # executions lookups (simulate some docs)
    exec_coll = mock_db.get_collection("executions")
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs
    exec_coll.find.return_value = Cursor([
        {"execution_id": "e1", "status": "completed"},
        {"execution_id": "e2", "status": "running"},
    ])

    detail = await repo.get_replay_status_with_progress("s2")
    assert detail and detail.session.status in (ReplaySessionStatus.RUNNING, ReplaySessionStatus.COMPLETED)
    assert isinstance(detail.execution_results, list)


@pytest.mark.asyncio
async def test_count_and_preview_helpers(repo: AdminEventsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    mock_db.events.count_documents = AsyncMock(return_value=42)
    assert await repo.count_events_for_replay({}) == 42

    # no query supplied -> empty preview
    preview = await repo.get_replay_events_preview()
    assert preview == {"events": [], "total": 0}


@pytest.mark.asyncio
async def test_browse_events_exception(repo: AdminEventsRepository, mock_db) -> None:
    mock_db.events.count_documents = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.browse_events(EventFilter())


@pytest.mark.asyncio
async def test_get_event_detail_exception(repo: AdminEventsRepository, mock_db) -> None:
    mock_db.events.find_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_event_detail("e1")


@pytest.mark.asyncio
async def test_delete_event_exception(repo: AdminEventsRepository, mock_db) -> None:
    mock_db.events.delete_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.delete_event("e1")


@pytest.mark.asyncio
async def test_get_event_stats_exception(repo: AdminEventsRepository, mock_db) -> None:
    # aggregate call raises
    mock_db.events.aggregate = MagicMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_event_stats(hours=1)


@pytest.mark.asyncio
async def test_export_events_csv_exception(repo: AdminEventsRepository, mock_db) -> None:
    class Cursor:
        def sort(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):  # pragma: no cover - not reached
            return []
    mock_db.events.find = MagicMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.export_events_csv(EventFilter())


@pytest.mark.asyncio
async def test_archive_and_replay_session_exceptions(repo: AdminEventsRepository, mock_db) -> None:
    # archive
    events_archive = mock_db.get_collection("events_archive")
    events_archive.insert_one = AsyncMock(side_effect=Exception("boom"))
    from app.domain.events.event_models import Event
    from app.infrastructure.kafka.events.metadata import EventMetadata
    from datetime import datetime, timezone
    ev = Event(event_id="e1", event_type="T", event_version="1", timestamp=datetime.now(timezone.utc), metadata=EventMetadata(service_name="s", service_version="1"), payload={})
    with pytest.raises(Exception):
        await repo.archive_event(ev, deleted_by="admin")

    # create replay session
    mock_db.replay_sessions.insert_one = AsyncMock(side_effect=Exception("boom"))
    from app.domain.admin.replay_models import ReplaySession
    from app.domain.events.event_models import ReplaySessionStatus
    from datetime import datetime, timezone
    rs = ReplaySession(
        session_id="s1",
        status=ReplaySessionStatus.SCHEDULED,
        total_events=0,
        correlation_id="corr",
        created_at=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        await repo.create_replay_session(rs)


@pytest.mark.asyncio
async def test_get_update_replay_session_exceptions(repo: AdminEventsRepository, mock_db) -> None:
    mock_db.replay_sessions.find_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_replay_session("s1")

    mock_db.replay_sessions.update_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.update_replay_session("s1", {"status": "running"})


@pytest.mark.asyncio
async def test_get_replay_status_with_progress_none(repo: AdminEventsRepository, mock_db) -> None:
    # No doc found -> returns None
    mock_db.replay_sessions.find_one = AsyncMock(return_value=None)
    assert await repo.get_replay_status_with_progress("missing") is None


@pytest.mark.asyncio
async def test_replay_supporting_methods_exceptions(repo: AdminEventsRepository, mock_db) -> None:
    # count_events_for_replay except
    mock_db.events.count_documents = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.count_events_for_replay({})

    # get_events_preview_for_replay except
    class Cursor:
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):  # pragma: no cover
            return []
    mock_db.events.find = MagicMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_events_preview_for_replay({}, limit=1)

    # get_replay_events_preview except
    mock_db.event_store.count_documents = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_replay_events_preview(event_ids=["e1"])  # triggers mapper and count
