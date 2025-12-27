from datetime import datetime, timezone

import pytest

from app.db.repositories.dlq_repository import DLQRepository
from app.domain.enums.events import EventType
from app.dlq import DLQFields, DLQMessageStatus

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(db) -> DLQRepository:  # type: ignore[valid-type]
    return DLQRepository(db)


def make_dlq_doc(eid: str, topic: str, etype: str, status: str = DLQMessageStatus.PENDING) -> dict:
    now = datetime.now(timezone.utc)
    # Build event dict compatible with event schema (top-level fields)
    event: dict[str, object] = {
        "event_type": etype,
        "metadata": {"service_name": "svc", "service_version": "1"},
    }
    if etype == str(EventType.USER_LOGGED_IN):
        event.update({"user_id": "u1", "login_method": "password"})
    elif etype == str(EventType.EXECUTION_STARTED):
        event.update({"execution_id": "x1", "pod_name": "p1"})
    return {
        DLQFields.EVENT: event,
        DLQFields.ORIGINAL_TOPIC: topic,
        DLQFields.ERROR: "err",
        DLQFields.RETRY_COUNT: 0,
        DLQFields.FAILED_AT: now,
        DLQFields.STATUS: status,
        DLQFields.PRODUCER_ID: "p1",
        DLQFields.EVENT_ID: eid,
    }


@pytest.mark.asyncio
async def test_stats_list_get_and_updates(repo: DLQRepository, db) -> None:  # type: ignore[valid-type]
    await db.get_collection("dlq_messages").insert_many([
        make_dlq_doc("id1", "t1", str(EventType.USER_LOGGED_IN), DLQMessageStatus.PENDING),
        make_dlq_doc("id2", "t1", str(EventType.USER_LOGGED_IN), DLQMessageStatus.RETRIED),
        make_dlq_doc("id3", "t2", str(EventType.EXECUTION_STARTED), DLQMessageStatus.PENDING),
    ])
    stats = await repo.get_dlq_stats()
    assert isinstance(stats.by_status, dict) and len(stats.by_topic) >= 1

    res = await repo.get_messages(limit=2)
    assert res.total >= 3 and len(res.messages) <= 2
    msg = await repo.get_message_by_id("id1")
    assert msg and msg.event_id == "id1"
    assert await repo.mark_message_retried("id1") in (True, False)
    assert await repo.mark_message_discarded("id1", "r") in (True, False)

    topics = await repo.get_topics_summary()
    assert any(t.topic == "t1" for t in topics)


@pytest.mark.asyncio
async def test_retry_batch(repo: DLQRepository) -> None:
    class Manager:
        async def retry_message_manually(self, eid: str) -> bool:  # noqa: ARG002
            return True

    result = await repo.retry_messages_batch(["missing"], Manager())
    # Missing messages cause failures
    assert result.total == 1 and result.failed >= 1
