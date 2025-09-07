import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

from app.db.repositories.dlq_repository import DLQRepository
from app.dlq.models import DLQFields, DLQMessageStatus
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.events.schema.schema_registry import SchemaRegistryManager


pytestmark = pytest.mark.unit


# mock_db fixture now provided by main conftest.py


@pytest.fixture()
def repo(mock_db) -> DLQRepository:
    return DLQRepository(mock_db)


@pytest.mark.asyncio
async def test_get_dlq_stats(repo: DLQRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # status pipeline results
    class Agg:
        def __init__(self, stage: str):
            self.stage = stage
        def __aiter__(self):
            async def gen():
                if self.stage == "status":
                    yield {"_id": "pending", "count": 2}
                elif self.stage == "topic":
                    yield {"_id": "t1", "count": 3, "avg_retry_count": 1.5}
                else:
                    yield {"_id": "typeA", "count": 4}
            return gen()
        async def to_list(self, n: int):  # noqa: ARG002
            # age stats
            return [{"min_age": 1.0, "max_age": 10.0, "avg_age": 5.0}]

    # Emulate three consecutive aggregate calls with different pipelines
    aggregates = [Agg("status"), Agg("topic"), Agg("etype"), Agg("age")]
    def _aggregate_side_effect(_pipeline):
        return aggregates.pop(0)

    mock_db.dlq_messages.aggregate = MagicMock(side_effect=_aggregate_side_effect)
    stats = await repo.get_dlq_stats()
    assert stats.by_status["pending"] == 2 and stats.by_topic[0].topic == "t1" and stats.by_event_type[0].event_type == "typeA"


@pytest.mark.asyncio
async def test_get_messages_and_by_id_and_updates(repo: DLQRepository, mock_db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch schema registry to avoid real mapping
    def fake_deserialize_json(data: dict):  # noqa: ARG001
        return UserLoggedInEvent(user_id="u1", login_method="password", metadata=EventMetadata(service_name="svc", service_version="1"))
    monkeypatch.setattr(SchemaRegistryManager, "deserialize_json", staticmethod(lambda data: fake_deserialize_json(data)))

    # find cursor
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
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
    doc = {
        DLQFields.EVENT: {"event_type": "UserLoggedIn", "user_id": "u1", "metadata": {"service_name": "svc", "service_version": "1"}},
        DLQFields.ORIGINAL_TOPIC: "t",
        DLQFields.ERROR: "err",
        DLQFields.RETRY_COUNT: 0,
        DLQFields.FAILED_AT: now,
        DLQFields.STATUS: DLQMessageStatus.PENDING,
        DLQFields.PRODUCER_ID: "p1",
        DLQFields.EVENT_ID: "id1",
    }
    mock_db.dlq_messages.count_documents = AsyncMock(return_value=1)
    mock_db.dlq_messages.find.return_value = Cursor([doc])
    res = await repo.get_messages(limit=1)
    assert res.total == 1 and len(res.messages) == 1 and res.messages[0].event_id == "id1"

    mock_db.dlq_messages.find_one = AsyncMock(return_value=doc)
    msg = await repo.get_message_by_id("id1")
    assert msg and msg.event_id == "id1"

    mock_db.dlq_messages.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.mark_message_retried("id1") is True
    assert await repo.mark_message_discarded("id1", "r") is True


@pytest.mark.asyncio
async def test_get_topics_summary_and_retry_batch(repo: DLQRepository, mock_db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    class Agg:
        def __aiter__(self):
            async def gen():
                yield {
                    "_id": "t1",
                    "count": 2,
                    "statuses": [DLQMessageStatus.PENDING, DLQMessageStatus.RETRIED],
                    "oldest_message": datetime.now(timezone.utc),
                    "newest_message": datetime.now(timezone.utc),
                    "avg_retry_count": 0.5,
                    "max_retry_count": 1,
                }
            return gen()

    mock_db.dlq_messages.aggregate = MagicMock(return_value=Agg())
    topics = await repo.get_topics_summary()
    assert len(topics) == 1 and topics[0].topic == "t1"

    # retry batch
    async def fake_get_message_for_retry(eid: str):  # noqa: ARG001
        return object()
    monkeypatch.setattr(repo, "get_message_for_retry", fake_get_message_for_retry)

    class Manager:
        async def retry_message_manually(self, eid: str) -> bool:  # noqa: ARG002
            return True

    result = await repo.retry_messages_batch(["a", "b"], Manager())
    assert result.total == 2 and result.successful == 2 and result.failed == 0


@pytest.mark.asyncio
async def test_retry_batch_branches(repo: DLQRepository, mock_db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    # missing message path
    async def get_missing(eid: str):  # noqa: ARG001
        return None
    monkeypatch.setattr(repo, "get_message_for_retry", get_missing)
    class Manager:
        async def retry_message_manually(self, eid: str) -> bool:  # noqa: ARG002
            return False
    res = await repo.retry_messages_batch(["x"], Manager())
    assert res.failed == 1 and res.successful == 0


@pytest.mark.asyncio
async def test_dlq_stats_and_topics_exceptions(repo: DLQRepository, mock_db) -> None:
    # any aggregate raising should propagate
    mock_db.dlq_messages.aggregate = MagicMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_dlq_stats()

    with pytest.raises(Exception):
        await repo.get_topics_summary()


@pytest.mark.asyncio
async def test_mark_updates_exceptions(repo: DLQRepository, mock_db) -> None:
    mock_db.dlq_messages.update_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.mark_message_retried("e1")

    mock_db.dlq_messages.update_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.mark_message_discarded("e1", "r")


@pytest.mark.asyncio
async def test_retry_messages_batch_exception_branch(repo: DLQRepository, mock_db, monkeypatch: pytest.MonkeyPatch) -> None:
    # Cause get_message_for_retry to raise -> triggers outer except path
    async def boom(_eid: str):
        raise RuntimeError("boom")
    monkeypatch.setattr(repo, "get_message_for_retry", boom)

    class Manager:
        async def retry_message_manually(self, eid: str) -> bool:  # noqa: ARG002
            return False

    res = await repo.retry_messages_batch(["x"], Manager())
    assert res.failed == 1 and len(res.details) == 1 and res.details[0].status == "failed"
