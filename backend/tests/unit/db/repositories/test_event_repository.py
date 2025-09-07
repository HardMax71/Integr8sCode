import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import DESCENDING

from app.db.repositories.event_repository import EventRepository
from app.domain.events.event_models import Event, EventFields, EventListResult
from app.infrastructure.kafka.events.metadata import EventMetadata


pytestmark = pytest.mark.unit


def make_event(event_id: str = "e1", user: str | None = "u1") -> Event:
    return Event(
        event_id=event_id,
        event_type="UserLoggedIn",
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata=EventMetadata(service_name="svc", service_version="1", user_id=user),
        payload={"k": 1},
        aggregate_id="agg1",
    )


@pytest.fixture()
def repo(mock_db) -> EventRepository:
    return EventRepository(mock_db)


@pytest.mark.asyncio
async def test_store_event_sets_stored_at_and_inserts(repo: EventRepository, mock_db: AsyncMock) -> None:
    ev = make_event("e1")
    # insert_one returns object with inserted_id
    mock_db.events.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid"))
    eid = await repo.store_event(ev)
    assert eid == "e1"
    mock_db.events.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_store_events_batch_success(repo: EventRepository, mock_db: AsyncMock) -> None:
    evs = [make_event("e1"), make_event("e2")]
    mock_db.events.insert_many = AsyncMock(return_value=MagicMock(inserted_ids=[1, 2]))
    ids = await repo.store_events_batch(evs)
    assert ids == ["e1", "e2"]


@pytest.mark.asyncio
async def test_get_event_found(repo: EventRepository, mock_db: AsyncMock) -> None:
    now = datetime.now(timezone.utc)
    mock_db.events.find_one = AsyncMock(return_value={
        EventFields.EVENT_ID: "e1",
        EventFields.EVENT_TYPE: "UserLoggedIn",
        EventFields.EVENT_VERSION: "1.0",
        EventFields.TIMESTAMP: now,
        EventFields.METADATA: EventMetadata(service_name="svc", service_version="1", user_id="u1").to_dict(),
        "custom": 123,
    })
    ev = await repo.get_event("e1")
    assert ev and ev.event_id == "e1" and ev.payload.get("custom") == 123
    mock_db.events.find_one.assert_called_once_with({EventFields.EVENT_ID: "e1"})


@pytest.mark.asyncio
async def test_get_events_by_type_builds_time_filter(repo: EventRepository, mock_db: AsyncMock) -> None:
    class Cursor:
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, length: int | None):  # noqa: ARG002
            return []

    mock_db.events.find.return_value = Cursor()
    await repo.get_events_by_type("t", start_time=1.0, end_time=2.0, limit=50, skip=5)
    q = mock_db.events.find.call_args[0][0]
    assert q[EventFields.EVENT_TYPE] == "t"
    assert EventFields.TIMESTAMP in q and "$gte" in q[EventFields.TIMESTAMP] and "$lte" in q[EventFields.TIMESTAMP]


@pytest.mark.asyncio
async def test_get_event_statistics_pipeline(repo: EventRepository, mock_db: AsyncMock) -> None:
    agg = AsyncMock()
    agg.to_list = AsyncMock(return_value=[{
        "by_type": [{"_id": "A", "count": 10}],
        "by_service": [{"_id": "svc", "count": 5}],
        "by_hour": [{"_id": "2024-01-01 10:00", "count": 3}],
        "total": [{"count": 12}],
    }])
    mock_db.events.aggregate = MagicMock(return_value=agg)
    stats = await repo.get_event_statistics()
    assert stats.total_events == 12 and stats.events_by_type["A"] == 10 and stats.events_by_service["svc"] == 5


@pytest.mark.asyncio
async def test_get_event_statistics_filtered(repo: EventRepository, mock_db: AsyncMock) -> None:
    agg = AsyncMock()
    agg.to_list = AsyncMock(return_value=[{
        "by_type": [],
        "by_service": [],
        "by_hour": [],
        "total": [],
    }])
    mock_db.events.aggregate = MagicMock(return_value=agg)
    stats = await repo.get_event_statistics_filtered(match={"x": 1})
    assert stats.total_events == 0 and stats.events_by_type == {}


@pytest.mark.asyncio
async def test_user_events_paginated_has_more(repo: EventRepository, mock_db: AsyncMock) -> None:
    # count = 15, skip=0, limit=10 => has_more True
    mock_db.events.count_documents = AsyncMock(return_value=15)

    class Cursor:
        def __init__(self):
            self._docs = [{EventFields.EVENT_ID: "e1", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: datetime.now(timezone.utc), EventFields.METADATA: EventMetadata(service_name="s", service_version="1", user_id="u1").to_dict()}]
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def __aiter__(self):  # pragma: no cover
            for d in self._docs:
                yield d
        async def to_list(self, *_a, **_k):  # pragma: no cover
            return self._docs

    mock_db.events.find.return_value = Cursor()
    res = await repo.get_user_events_paginated("u1", limit=10)
    assert isinstance(res, EventListResult)
    assert res.total == 15 and res.has_more is True


@pytest.mark.asyncio
async def test_cleanup_old_events_dry_run_and_delete(repo: EventRepository, mock_db: AsyncMock) -> None:
    mock_db.events.count_documents = AsyncMock(return_value=9)
    n = await repo.cleanup_old_events(older_than_days=1, event_types=["X"], dry_run=True)
    assert n == 9

    mock_db.events.delete_many = AsyncMock(return_value=AsyncMock(deleted_count=4))
    n2 = await repo.cleanup_old_events(older_than_days=1, event_types=None, dry_run=False)
    assert n2 == 4


@pytest.mark.asyncio
async def test_query_events_generic(repo: EventRepository, mock_db: AsyncMock) -> None:
    mock_db.events.count_documents = AsyncMock(return_value=1)

    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def find(self, *_a, **_k):  # pragma: no cover
            return self
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    now = datetime.now(timezone.utc)
    docs = [{
        EventFields.EVENT_ID: "e1",
        EventFields.EVENT_TYPE: "X",
        EventFields.TIMESTAMP: now,
        EventFields.METADATA: EventMetadata(service_name="svc", service_version="1").to_dict(),
    }]
    mock_db.events.find.return_value = Cursor(docs)
    result = await repo.query_events_generic({}, EventFields.TIMESTAMP, DESCENDING, 0, 10)
    assert result.total == 1 and len(result.events) == 1 and result.events[0].event_id == "e1"


@pytest.mark.asyncio
async def test_aggregate_and_list_types_and_misc_queries(repo: EventRepository, mock_db: AsyncMock) -> None:
    # aggregate_events
    class Agg:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()
    mock_db.events.aggregate = MagicMock(return_value=Agg([{"_id": {"x": 1}, "v": 2}]))
    agg_res = await repo.aggregate_events([{"$match": {}}], limit=5)
    assert agg_res.to_list()[0]["_id"] == "{'x': 1}" or isinstance(agg_res.to_list()[0]["_id"], str)

    # list_event_types
    class Agg2:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()
    mock_db.events.aggregate = MagicMock(return_value=Agg2([{"_id": "A"}, {"_id": "B"}]))
    types = await repo.list_event_types(match={"x": 1})
    assert types == ["A", "B"]

    # get_events_by_aggregate
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
    mock_db.events.find.return_value = Cursor([{EventFields.EVENT_ID: "e1", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="s", service_version="1").to_dict()}])
    evs = await repo.get_events_by_aggregate("agg")
    assert len(evs) == 1

    # get_events_by_correlation
    class Cursor2(Cursor):
        pass
    mock_db.events.find.return_value = Cursor2([{EventFields.EVENT_ID: "e2", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="s", service_version="1").to_dict()}])
    _ = await repo.get_events_by_correlation("corr")

    # get_events_by_user
    mock_db.events.find.return_value = Cursor([{EventFields.EVENT_ID: "e3", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="s", service_version="1", user_id="u1").to_dict()}])
    _ = await repo.get_events_by_user("u1", event_types=["T"], start_time=now, end_time=now, limit=1, skip=0)

    # get_execution_events
    mock_db.events.find.return_value = Cursor([{EventFields.EVENT_ID: "e4", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="s", service_version="1").to_dict()}])
    _ = await repo.get_execution_events("exec1")


@pytest.mark.asyncio
async def test_stream_and_replay_info(repo: EventRepository, mock_db: AsyncMock) -> None:
    # stream_events: mock watch context manager
    class FakeStream:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):  # noqa: D401, ANN001
            return False
        def __aiter__(self):
            async def gen():
                yield {"operationType": "insert", "fullDocument": {"x": 1}}
                yield {"operationType": "update", "fullDocument": {"x": 2}}
                yield {"operationType": "delete"}
            return gen()

    mock_db.events.watch = MagicMock(return_value=FakeStream())
    it = repo.stream_events(filters={"op": 1}, start_after=None)
    results = []
    async for doc in it:
        results.append(doc)
    assert results == [{"x": 1}, {"x": 2}]

    # replay info when no events
    async def no_events(_aggregate_id: str, limit: int = 10000):  # noqa: ARG001
        return []
    repo.get_aggregate_events_for_replay = no_events  # type: ignore[assignment]
    assert await repo.get_aggregate_replay_info("agg") is None

    # replay info with events
    now = datetime.now(timezone.utc)
    e = make_event("e10")
    async def some_events(_aggregate_id: str, limit: int = 10000):  # noqa: ARG001
        return [e]
    repo.get_aggregate_events_for_replay = some_events  # type: ignore[assignment]
    info = await repo.get_aggregate_replay_info("agg")
    assert info and info.event_count == 1


@pytest.mark.asyncio
async def test_delete_event_with_archival(repo: EventRepository, mock_db: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch repo.get_event to return a full Event
    async def _get_event(_event_id: str):
        return make_event("e7")
    monkeypatch.setattr(repo, "get_event", _get_event)

    # archive collection via ["events_archive"]
    mock_db["events_archive"].insert_one = AsyncMock()
    mock_db.events.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

    archived = await repo.delete_event_with_archival("e7", deleted_by="admin", deletion_reason="test")
    assert archived and archived.event_id == "e7" and archived.deleted_by == "admin"


@pytest.mark.asyncio
async def test_query_events_advanced_access_control(repo: EventRepository, mock_db: AsyncMock) -> None:
    # when filters.user_id mismatches and user_role != admin -> None
    from app.domain.events.event_models import EventFilter
    res = await repo.query_events_advanced(user_id="u1", user_role="user", filters=EventFilter(user_id="u2"))
    assert res is None


# Additional tests from test_event_repository_more.py
def make_event_more(event_id: str = "eX", user: str | None = "u1") -> Event:
    return Event(
        event_id=event_id,
        event_type="TypeA",
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata=EventMetadata(service_name="svc", service_version="1", user_id=user),
        payload={"ok": True},
        aggregate_id="agg",
    )


def test_build_query_branches(repo: EventRepository) -> None:
    q = repo._build_query(time_range=(1.0, 2.0), event_types=["A", "B"], other=123, none_val=None)
    assert EventFields.TIMESTAMP in q and "$gte" in q[EventFields.TIMESTAMP] and "$lte" in q[EventFields.TIMESTAMP]
    assert q[EventFields.EVENT_TYPE] == {"$in": ["A", "B"]}
    assert q["other"] == 123 and "none_val" not in q


@pytest.mark.asyncio
async def test_store_event_duplicate_and_exception(repo: EventRepository, mock_db) -> None:
    from pymongo.errors import DuplicateKeyError
    ev = make_event_more("dup")
    mock_db.events.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))
    with pytest.raises(DuplicateKeyError):
        await repo.store_event(ev)

    mock_db.events.insert_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.store_event(ev)


@pytest.mark.asyncio
async def test_store_events_batch_empty_and_fallback(repo: EventRepository, mock_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from pymongo.errors import DuplicateKeyError
    # empty -> []
    assert await repo.store_events_batch([]) == []

    # insert_many error -> fallback to per-item store_event
    ev1, ev2 = make_event_more("e1"), make_event_more("e2")
    mock_db.events.insert_many = AsyncMock(side_effect=Exception("boom"))

    called: list[str] = []
    async def _store_event(e: Event) -> str:
        called.append(e.event_id)
        if e.event_id == "e2":
            raise DuplicateKeyError("dup")
        return e.event_id
    monkeypatch.setattr(repo, "store_event", _store_event)

    ids = await repo.store_events_batch([ev1, ev2])
    assert ids == ["e1"] and called == ["e1", "e2"]


@pytest.mark.asyncio
async def test_get_event_error_returns_none(repo: EventRepository, mock_db) -> None:
    mock_db.events.find_one = AsyncMock(side_effect=Exception("boom"))
    assert await repo.get_event("e1") is None


@pytest.mark.asyncio
async def test_search_events_and_stats_defaults(repo: EventRepository, mock_db) -> None:
    # search_events
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
    mock_db.events.find.return_value = Cursor([{EventFields.EVENT_ID: "e1", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="s", service_version="1").to_dict()}])
    evs = await repo.search_events("text", filters={"x": 1})
    assert len(evs) == 1 and evs[0].event_id == "e1"

    # get_event_statistics no result -> default return path
    agg = AsyncMock(); agg.to_list = AsyncMock(return_value=[])
    mock_db.events.aggregate = MagicMock(return_value=agg)
    stats = await repo.get_event_statistics(start_time=1.0, end_time=2.0)
    assert stats.total_events == 0 and stats.events_by_type == {}


@pytest.mark.asyncio
async def test_get_event_statistics_filtered_time(repo: EventRepository, mock_db) -> None:
    agg = AsyncMock(); agg.to_list = AsyncMock(return_value=[{"by_type": [], "by_service": [], "by_hour": [], "total": []}])
    mock_db.events.aggregate = MagicMock(return_value=agg)
    _ = await repo.get_event_statistics_filtered(match={"x": 1}, start_time=datetime.now(timezone.utc), end_time=datetime.now(timezone.utc))
    # No assertions beyond successful call; covers time filter branch


@pytest.mark.asyncio
async def test_delete_event_with_archival_not_found_and_failed_delete(repo: EventRepository, mock_db, monkeypatch: pytest.MonkeyPatch) -> None:
    # Not found -> None
    async def _get_none(_eid: str):
        return None
    monkeypatch.setattr(repo, "get_event", _get_none)
    assert await repo.delete_event_with_archival("missing", deleted_by="admin") is None

    # Found but delete deleted_count == 0 -> raises
    async def _get_event(_eid: str):
        return make_event_more("eX")
    monkeypatch.setattr(repo, "get_event", _get_event)
    mock_db["events_archive"].insert_one = AsyncMock()
    mock_db.events.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
    with pytest.raises(Exception):
        await repo.delete_event_with_archival("eX", deleted_by="admin")


@pytest.mark.asyncio
async def test_query_events_advanced_authorized(repo: EventRepository, mock_db) -> None:
    # Authorized path with filters applied
    mock_db.events.count_documents = AsyncMock(return_value=1)
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def __aiter__(self):  # pragma: no cover
            for d in self._docs:
                yield d
        async def to_list(self, *_a, **_k):
            return self._docs
    now = datetime.now(timezone.utc)
    mock_db.events.find.return_value = Cursor([{EventFields.EVENT_ID: "e1", EventFields.EVENT_TYPE: "T", EventFields.TIMESTAMP: now, EventFields.METADATA: EventMetadata(service_name="s", service_version="1").to_dict()}])
    from app.domain.events.event_models import EventFilter
    res = await repo.query_events_advanced(user_id="u1", user_role="admin", filters=EventFilter(user_id="u1"))
    assert res and res.total == 1 and len(res.events) == 1
