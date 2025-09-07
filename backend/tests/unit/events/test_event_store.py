import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock, patch

import pytest
from pymongo.errors import BulkWriteError, DuplicateKeyError
from pymongo import ASCENDING, DESCENDING

from app.events.event_store import EventStore, create_event_store
from app.domain.enums.events import EventType
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent, ExecutionCompletedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.base import BaseEvent


class FakeCursor:
    def __init__(self, docs):  # noqa: ANN001
        self._docs = docs
        self._i = 0
        self._skip = 0
        self._limit = None

    def sort(self, *args, **kwargs):  # noqa: ANN001
        return self

    def skip(self, n):  # noqa: ANN001
        self._skip = n
        return self

    def limit(self, n):  # noqa: ANN001
        self._limit = n
        return self

    async def __aiter__(self):
        count = 0
        for i, d in enumerate(self._docs):
            if i >= self._skip:
                if self._limit is not None and count >= self._limit:
                    break
                yield d
                count += 1

    async def to_list(self, n):  # noqa: ANN001
        result = self._docs[self._skip:]
        if self._limit is not None:
            result = result[:self._limit]
        return result


class FakeCollection:
    def __init__(self):
        self.docs = {}
        self._indexes = []

    def __getitem__(self, k):  # noqa: ANN001
        return self.docs[k]

    def list_indexes(self):
        # Motor returns a cursor synchronously; .to_list is awaited
        return FakeCursor([{"name": "_id_"}])

    async def create_indexes(self, idx):  # noqa: ANN001
        self._indexes.extend(idx)

    async def insert_one(self, doc):  # noqa: ANN001
        _id = doc.get("event_id")
        if _id in self.docs:
            raise DuplicateKeyError("dup")
        self.docs[_id] = doc
        return SimpleNamespace(inserted_id=_id)

    async def insert_many(self, docs, ordered=False):  # noqa: ANN001
        inserted = []
        errors = []
        for i, d in enumerate(docs):
            _id = d.get("event_id")
            if _id in self.docs:
                errors.append({"code": 11000, "index": i})
            else:
                self.docs[_id] = d
                inserted.append(_id)
        if errors:
            raise BulkWriteError({"writeErrors": errors})
        return SimpleNamespace(inserted_ids=inserted)

    def find(self, q, proj):  # noqa: ANN001
        # return all docs matching keys in q (very simplified)
        out = []
        for d in self.docs.values():
            match = True
            for k, v in q.items():
                if k == "timestamp" and isinstance(v, dict):
                    continue
                if d.get(k) != v:
                    match = False
                    break
            if match:
                out.append(d)
        return FakeCursor(out)

    async def find_one(self, q, proj):  # noqa: ANN001
        for d in self.docs.values():
            ok = True
            for k, v in q.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                return d
        return None


class DummySchema:
    def deserialize_json(self, data):  # noqa: ANN001
        # Build a PodCreatedEvent for tests
        return PodCreatedEvent(
            execution_id=data.get("execution_id", "e"),
            pod_name=data.get("pod_name", "p"),
            namespace=data.get("namespace", "n"),
            metadata=EventMetadata(service_name="s", service_version="1"),
        )


@pytest.mark.asyncio
async def test_store_event_and_queries():
    # Use a dict for db since EventStore expects subscriptable object
    db = {"events": FakeCollection()}
    store = EventStore(db=db, schema_registry=DummySchema())
    await store.initialize()

    ev = PodCreatedEvent(execution_id="x1", pod_name="pod1", namespace="ns", metadata=EventMetadata(service_name="s", service_version="1"))
    ok = await store.store_event(ev)
    assert ok is True
    # Duplicate
    ok2 = await store.store_event(ev)
    assert ok2 is True

    # Batch insert with one duplicate
    ev2 = PodCreatedEvent(execution_id="x2", pod_name="pod2", namespace="ns", metadata=EventMetadata(service_name="s", service_version="1"))
    res = await store.store_batch([ev, ev2])
    assert res["total"] == 2
    assert res["stored"] >= 1

    # get_by_id equivalent via type lookup
    from app.domain.enums.events import EventType
    fetched_list = await store.get_events_by_type(EventType.POD_CREATED)
    assert any(e.execution_id == "x1" for e in fetched_list)

    # get by type
    from app.domain.enums.events import EventType

    items = await store.get_events_by_type(EventType.POD_CREATED)
    assert isinstance(items, list)

    items2 = await store.get_execution_events("x1")
    assert items2

    items3 = await store.get_user_events("u1")
    assert isinstance(items3, list)

    items4 = await store.get_security_events()
    assert isinstance(items4, list)

    items5 = await store.get_correlation_chain("cid")
    assert isinstance(items5, list)

    # Replay with callback
    called = {"n": 0}

    async def cb(_):  # noqa: ANN001
        called["n"] += 1

    start = datetime.now(timezone.utc) - timedelta(days=1)
    cnt = await store.replay_events(start_time=start, callback=cb)
    assert cnt >= 1
    assert called["n"] >= 1
class AsyncIteratorMock:
    """Mock async iterator for cursor objects"""
    def __init__(self, items):
        self.items = list(items)  # Make a copy
        self.sort_mock = Mock(return_value=self)
        self.skip_mock = Mock(return_value=self)
        self.limit_mock = Mock(return_value=self)
        
    def sort(self, *args):
        return self.sort_mock(*args)
        
    def skip(self, offset):
        return self.skip_mock(offset)
        
    def limit(self, n):
        if n:
            return self.limit_mock(n)
        return self
        
    def __aiter__(self):
        return self
        
    async def __anext__(self):
        if self.items:
            return self.items.pop(0)
        raise StopAsyncIteration


@pytest.fixture
def mock_db():
    """Mock MongoDB database"""
    db = AsyncMock()
    db.command = AsyncMock(return_value={"ok": 1})
    return db


@pytest.fixture
def mock_schema_registry():
    """Mock SchemaRegistryManager"""
    registry = Mock()
    registry.deserialize_json = Mock(side_effect=lambda doc: create_mock_event(doc))
    return registry


@pytest.fixture
def mock_metrics():
    """Mock event metrics"""
    metrics = Mock()
    metrics.record_event_store_duration = Mock()
    metrics.record_event_stored = Mock()
    metrics.record_event_store_failed = Mock()
    metrics.record_event_query_duration = Mock()
    return metrics


@pytest.fixture
def event_store(mock_db, mock_schema_registry, mock_metrics):
    """Create EventStore with mocked dependencies"""
    with patch('app.events.event_store.get_event_metrics', return_value=mock_metrics):
        store = EventStore(
            db=mock_db,
            schema_registry=mock_schema_registry,
            collection_name="events",
            ttl_days=90,
            batch_size=100
        )
        # Set up mock collection
        store.collection = AsyncMock()
        return store


def create_mock_event(doc=None):
    """Helper to create mock event from document"""
    if doc is None:
        doc = {}
    
    event = Mock(spec=BaseEvent)
    event.event_id = doc.get("event_id", "test_event_123")
    event.event_type = doc.get("event_type", EventType.EXECUTION_REQUESTED)
    event.model_dump = Mock(return_value=doc)
    return event


@pytest.mark.asyncio
async def test_initialize_already_initialized(event_store):
    """Test initialize when already initialized"""
    event_store._initialized = True
    
    await event_store.initialize()
    
    # Should return early without doing anything
    event_store.collection.list_indexes.assert_not_called()


@pytest.mark.asyncio
async def test_initialize_creates_indexes(event_store):
    """Test initialize creates indexes when collection is empty"""
    event_store._initialized = False
    
    # Mock empty index list (only default _id index)
    mock_cursor = Mock()
    mock_cursor.to_list = AsyncMock(return_value=[{"name": "_id_"}])
    event_store.collection.list_indexes = Mock(return_value=mock_cursor)
    
    await event_store.initialize()
    
    # Should create indexes
    event_store.collection.create_indexes.assert_called_once()
    assert event_store._initialized is True


@pytest.mark.asyncio
async def test_store_event_duplicate_key(event_store):
    """Test store_event handles duplicate key error"""
    event = create_mock_event({"event_id": "dup_123", "event_type": "execution_requested"})
    
    # Mock DuplicateKeyError
    event_store.collection.insert_one.side_effect = DuplicateKeyError("Duplicate key")
    
    result = await event_store.store_event(event)
    
    # Should return True for duplicate (idempotent)
    assert result is True


@pytest.mark.asyncio
async def test_store_event_generic_exception(event_store):
    """Test store_event handles generic exceptions"""
    event = create_mock_event({"event_id": "fail_123", "event_type": "execution_requested"})
    
    # Mock generic exception
    event_store.collection.insert_one.side_effect = Exception("Database error")
    
    result = await event_store.store_event(event)
    
    # Should return False and record failure
    assert result is False
    event_store.metrics.record_event_store_failed.assert_called_once()


@pytest.mark.asyncio
async def test_store_batch_empty_list(event_store):
    """Test store_batch with empty event list"""
    result = await event_store.store_batch([])
    
    assert result == {"total": 0, "stored": 0, "duplicates": 0, "failed": 0}
    event_store.collection.insert_many.assert_not_called()


@pytest.mark.asyncio
async def test_store_batch_bulk_write_error_duplicates(event_store):
    """Test store_batch handles BulkWriteError with duplicates"""
    events = [
        create_mock_event({"event_id": f"event_{i}", "event_type": "execution_requested"})
        for i in range(3)
    ]
    
    # Mock BulkWriteError with duplicate key errors
    error = BulkWriteError({
        "writeErrors": [
            {"code": 11000, "errmsg": "duplicate key"},  # Duplicate
            {"code": 11000, "errmsg": "duplicate key"},  # Duplicate
            {"code": 12345, "errmsg": "other error"},    # Other error
        ]
    })
    event_store.collection.insert_many.side_effect = error
    
    result = await event_store.store_batch(events)
    
    assert result["total"] == 3
    assert result["duplicates"] == 2
    assert result["failed"] == 1
    assert result["stored"] == 0


@pytest.mark.asyncio
async def test_store_batch_non_bulk_write_error(event_store):
    """Test store_batch handles non-BulkWriteError exceptions"""
    events = [create_mock_event({"event_id": "event_1"})]
    
    # Mock a non-BulkWriteError exception
    event_store.collection.insert_many.side_effect = ValueError("Invalid data")
    
    result = await event_store.store_batch(events)
    
    assert result["total"] == 1
    assert result["stored"] == 0
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_store_batch_records_metrics_for_stored_events(event_store):
    """Test store_batch records metrics when events are stored"""
    events = [
        create_mock_event({"event_id": f"event_{i}", "event_type": EventType.EXECUTION_REQUESTED})
        for i in range(3)
    ]
    
    # Mock successful insert
    mock_result = Mock()
    mock_result.inserted_ids = ["id1", "id2", "id3"]
    event_store.collection.insert_many.return_value = mock_result
    
    result = await event_store.store_batch(events)
    
    assert result["stored"] == 3
    # Should record metrics for each stored event
    assert event_store.metrics.record_event_stored.call_count == 3


@pytest.mark.asyncio
async def test_get_event_found(event_store):
    """Test get_event when event exists"""
    event_id = "test_123"
    doc = {"event_id": event_id, "event_type": "execution_requested"}
    
    event_store.collection.find_one.return_value = doc
    
    result = await event_store.get_event(event_id)
    
    assert result is not None
    assert result.event_id == event_id
    event_store.metrics.record_event_query_duration.assert_called_once()


@pytest.mark.asyncio
async def test_get_event_not_found(event_store):
    """Test get_event when event doesn't exist"""
    event_store.collection.find_one.return_value = None
    
    result = await event_store.get_event("nonexistent")
    
    assert result is None


@pytest.mark.asyncio
async def test_get_events_by_type_with_time_range(event_store):
    """Test get_events_by_type with time range"""
    start_time = datetime.now(timezone.utc) - timedelta(days=1)
    end_time = datetime.now(timezone.utc)
    
    # Mock cursor
    mock_cursor = AsyncIteratorMock([
        {"event_id": "1", "event_type": "execution_requested"}
    ])
    event_store.collection.find = Mock(return_value=mock_cursor)
    
    await event_store.get_events_by_type(
        EventType.EXECUTION_REQUESTED,
        start_time=start_time,
        end_time=end_time
    )
    
    # Check that time range was included in query
    call_args = event_store.collection.find.call_args[0][0]
    assert "timestamp" in call_args
    assert "$gte" in call_args["timestamp"]
    assert "$lte" in call_args["timestamp"]


@pytest.mark.asyncio
async def test_get_execution_events_with_event_types(event_store):
    """Test get_execution_events with event type filtering"""
    execution_id = "exec_123"
    event_types = [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED]
    
    # Mock cursor
    mock_cursor = AsyncIteratorMock([])
    event_store.collection.find = Mock(return_value=mock_cursor)
    
    await event_store.get_execution_events(execution_id, event_types)
    
    # Check that event types were included in query
    call_args = event_store.collection.find.call_args[0][0]
    assert "event_type" in call_args
    assert "$in" in call_args["event_type"]
    assert "execution_requested" in call_args["event_type"]["$in"]


@pytest.mark.asyncio
async def test_get_user_events_with_filters(event_store):
    """Test get_user_events with all filters"""
    user_id = "user_123"
    event_types = ["execution_requested"]
    start_time = datetime.now(timezone.utc) - timedelta(days=1)
    end_time = datetime.now(timezone.utc)
    
    # Mock cursor
    mock_cursor = AsyncIteratorMock([])
    event_store.collection.find = Mock(return_value=mock_cursor)
    
    await event_store.get_user_events(
        user_id=user_id,
        event_types=event_types,
        start_time=start_time,
        end_time=end_time
    )
    
    # Check query construction
    call_args = event_store.collection.find.call_args[0][0]
    assert call_args["metadata.user_id"] == user_id
    assert "event_type" in call_args
    assert "timestamp" in call_args


@pytest.mark.asyncio
async def test_get_security_events_with_user_and_time(event_store):
    """Test get_security_events with user_id and time range"""
    user_id = "user_123"
    start_time = datetime.now(timezone.utc) - timedelta(hours=1)
    end_time = datetime.now(timezone.utc)
    
    # Mock cursor
    mock_cursor = AsyncIteratorMock([])
    event_store.collection.find = Mock(return_value=mock_cursor)
    
    await event_store.get_security_events(
        start_time=start_time,
        end_time=end_time,
        user_id=user_id
    )
    
    # Check query construction
    call_args = event_store.collection.find.call_args[0][0]
    assert call_args["metadata.user_id"] == user_id
    assert "timestamp" in call_args
    assert "$gte" in call_args["timestamp"]
    assert "$lte" in call_args["timestamp"]


@pytest.mark.asyncio
async def test_replay_events_with_filters_and_callback(event_store):
    """Test replay_events with all filters and callback"""
    start_time = datetime.now(timezone.utc) - timedelta(days=1)
    end_time = datetime.now(timezone.utc)
    event_types = [EventType.EXECUTION_REQUESTED]
    
    # Mock cursor that returns events
    mock_events = [
        {"event_id": "1", "event_type": "execution_requested"},
        {"event_id": "2", "event_type": "execution_requested"}
    ]
    mock_cursor = AsyncIteratorMock(mock_events)
    event_store.collection.find = Mock(return_value=mock_cursor)
    
    # Mock callback
    callback = AsyncMock()
    
    count = await event_store.replay_events(
        start_time=start_time,
        end_time=end_time,
        event_types=event_types,
        callback=callback
    )
    
    assert count == 2
    assert callback.call_count == 2
    
    # Check query construction
    call_args = event_store.collection.find.call_args[0][0]
    assert "$gte" in call_args["timestamp"]
    assert "$lte" in call_args["timestamp"]
    assert "event_type" in call_args


@pytest.mark.asyncio
async def test_replay_events_exception_handling(event_store):
    """Test replay_events handles exceptions"""
    start_time = datetime.now(timezone.utc)
    
    # Mock cursor that raises exception
    mock_cursor = AsyncMock()
    mock_cursor.sort.return_value = mock_cursor
    mock_cursor.__aiter__.side_effect = Exception("Database error")
    event_store.collection.find.return_value = mock_cursor
    
    count = await event_store.replay_events(start_time)
    
    # Should return 0 on error
    assert count == 0


@pytest.mark.asyncio
async def test_get_event_stats_with_time_range(event_store):
    """Test get_event_stats with time range filter"""
    start_time = datetime.now(timezone.utc) - timedelta(days=7)
    end_time = datetime.now(timezone.utc)
    
    # Mock aggregation cursor
    mock_cursor = AsyncIteratorMock([
        {
            "_id": "execution_requested",
            "count": 100,
            "first_event": start_time,
            "last_event": end_time
        },
        {
            "_id": "execution_completed",
            "count": 80,
            "first_event": start_time,
            "last_event": end_time
        }
    ])
    event_store.collection.aggregate = Mock(return_value=mock_cursor)
    
    stats = await event_store.get_event_stats(start_time, end_time)
    
    assert stats["total_events"] == 180
    assert "execution_requested" in stats["event_types"]
    assert stats["event_types"]["execution_requested"]["count"] == 100
    assert stats["event_types"]["execution_completed"]["count"] == 80
    
    # Check that time range was included in pipeline
    pipeline = event_store.collection.aggregate.call_args[0][0]
    assert pipeline[0]["$match"]["timestamp"]["$gte"] == start_time
    assert pipeline[0]["$match"]["timestamp"]["$lte"] == end_time


@pytest.mark.asyncio
async def test_get_event_stats_no_time_range(event_store):
    """Test get_event_stats without time range"""
    # Mock aggregation cursor
    mock_cursor = AsyncIteratorMock([
        {
            "_id": "execution_requested",
            "count": 50,
            "first_event": datetime.now(timezone.utc),
            "last_event": datetime.now(timezone.utc)
        }
    ])
    event_store.collection.aggregate = Mock(return_value=mock_cursor)
    
    stats = await event_store.get_event_stats()
    
    assert stats["total_events"] == 50
    
    # Pipeline should not have $match stage for time
    pipeline = event_store.collection.aggregate.call_args[0][0]
    assert pipeline[0].get("$match") is None or "timestamp" not in pipeline[0].get("$match", {})


def test_time_range_both_times(event_store):
    """Test _time_range with both start and end times"""
    start_time = datetime.now(timezone.utc) - timedelta(days=1)
    end_time = datetime.now(timezone.utc)
    
    result = event_store._time_range(start_time, end_time)
    
    assert result == {"$gte": start_time, "$lte": end_time}


def test_time_range_start_only(event_store):
    """Test _time_range with only start time"""
    start_time = datetime.now(timezone.utc)
    
    result = event_store._time_range(start_time, None)
    
    assert result == {"$gte": start_time}


def test_time_range_end_only(event_store):
    """Test _time_range with only end time"""
    end_time = datetime.now(timezone.utc)
    
    result = event_store._time_range(None, end_time)
    
    assert result == {"$lte": end_time}


def test_time_range_neither(event_store):
    """Test _time_range with neither start nor end time"""
    result = event_store._time_range(None, None)
    
    assert result is None


@pytest.mark.asyncio
async def test_health_check_success(event_store, mock_db):
    """Test successful health check"""
    event_store.collection.count_documents.return_value = 12345
    event_store._initialized = True
    
    result = await event_store.health_check()
    
    assert result["healthy"] is True
    assert result["event_count"] == 12345
    assert result["collection"] == "events"
    assert result["initialized"] is True
    mock_db.command.assert_called_once_with("ping")


@pytest.mark.asyncio
async def test_health_check_failure(event_store, mock_db):
    """Test health check when database is down"""
    mock_db.command.side_effect = Exception("Connection failed")
    
    result = await event_store.health_check()
    
    assert result["healthy"] is False
    assert "error" in result
    assert "Connection failed" in result["error"]


def test_create_event_store():
    """Test create_event_store factory function"""
    mock_db = MagicMock()
    mock_collection = Mock()
    mock_db.__getitem__.return_value = mock_collection
    mock_registry = Mock()
    
    with patch('app.events.event_store.get_event_metrics'):
        store = create_event_store(
            db=mock_db,
            schema_registry=mock_registry,
            collection_name="test_events",
            ttl_days=30,
            batch_size=50
        )
    
    assert isinstance(store, EventStore)
    assert store.collection_name == "test_events"
    assert store.ttl_days == 30
    assert store.batch_size == 50