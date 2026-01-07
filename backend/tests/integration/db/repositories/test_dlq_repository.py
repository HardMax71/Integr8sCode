import logging
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from app.core.database_context import Database
from app.db.docs import DLQMessageDocument
from app.db.repositories.dlq_repository import DLQRepository
from app.dlq import DLQMessageStatus
from app.domain.enums.events import EventType

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.db.repositories.dlq_repository")


@pytest.fixture
def repo() -> DLQRepository:
    return DLQRepository(_test_logger)


async def create_dlq_doc(
    event_id: str,
    topic: str,
    status: DLQMessageStatus = DLQMessageStatus.PENDING,
    event_type: EventType = EventType.USER_LOGGED_IN,
) -> DLQMessageDocument:
    """Create and insert a DLQ document with given parameters."""
    doc = DLQMessageDocument(
        event_id=event_id,
        event_type=str(event_type),
        event={
            "event_type": str(event_type),
            "metadata": {"service_name": "test", "service_version": "1"},
            "user_id": "u1",
            "login_method": "password",
        },
        original_topic=topic,
        error="test error",
        retry_count=0,
        failed_at=datetime.now(timezone.utc),
        status=status,
        producer_id="test",
    )
    await doc.insert()
    return doc


@pytest.mark.asyncio
async def test_get_message_by_id(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    event_id = unique_id("dlq-")
    topic = unique_id("topic-")

    await create_dlq_doc(event_id, topic)

    msg = await repo.get_message_by_id(event_id)
    assert msg is not None
    assert msg.event_id == event_id
    assert msg.original_topic == topic
    assert msg.status == DLQMessageStatus.PENDING


@pytest.mark.asyncio
async def test_get_message_by_id_not_found(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    msg = await repo.get_message_by_id(unique_id("nonexistent-"))
    assert msg is None


@pytest.mark.asyncio
async def test_mark_message_retried(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    event_id = unique_id("dlq-")
    topic = unique_id("topic-")

    await create_dlq_doc(event_id, topic, status=DLQMessageStatus.PENDING)

    result = await repo.mark_message_retried(event_id)
    assert result is True

    # Verify status changed
    msg = await repo.get_message_by_id(event_id)
    assert msg is not None
    assert msg.status == DLQMessageStatus.RETRIED
    assert msg.retried_at is not None


@pytest.mark.asyncio
async def test_mark_message_retried_not_found(
    repo: DLQRepository, db: Database, unique_id: Callable[[str], str]
) -> None:
    result = await repo.mark_message_retried(unique_id("nonexistent-"))
    assert result is False


@pytest.mark.asyncio
async def test_mark_message_discarded(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    event_id = unique_id("dlq-")
    topic = unique_id("topic-")

    await create_dlq_doc(event_id, topic, status=DLQMessageStatus.PENDING)

    result = await repo.mark_message_discarded(event_id, "test reason")
    assert result is True

    # Verify status changed
    msg = await repo.get_message_by_id(event_id)
    assert msg is not None
    assert msg.status == DLQMessageStatus.DISCARDED
    assert msg.discarded_at is not None
    assert msg.discard_reason == "test reason"


@pytest.mark.asyncio
async def test_mark_message_discarded_not_found(
    repo: DLQRepository, db: Database, unique_id: Callable[[str], str]
) -> None:
    result = await repo.mark_message_discarded(unique_id("nonexistent-"), "reason")
    assert result is False


@pytest.mark.asyncio
async def test_get_messages_with_pagination(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    topic = unique_id("topic-")
    event_ids = [unique_id(f"dlq-{i}-") for i in range(5)]

    for eid in event_ids:
        await create_dlq_doc(eid, topic)

    # Get first page
    result = await repo.get_messages(topic=topic, limit=2, offset=0)
    assert result.total == 5
    assert len(result.messages) == 2
    assert result.limit == 2
    assert result.offset == 0

    # Get second page
    result2 = await repo.get_messages(topic=topic, limit=2, offset=2)
    assert result2.total == 5
    assert len(result2.messages) == 2
    assert result2.offset == 2


@pytest.mark.asyncio
async def test_get_messages_filter_by_status(
    repo: DLQRepository, db: Database, unique_id: Callable[[str], str]
) -> None:
    topic = unique_id("topic-")

    await create_dlq_doc(unique_id("dlq-1-"), topic, status=DLQMessageStatus.PENDING)
    await create_dlq_doc(unique_id("dlq-2-"), topic, status=DLQMessageStatus.PENDING)
    await create_dlq_doc(unique_id("dlq-3-"), topic, status=DLQMessageStatus.RETRIED)

    pending = await repo.get_messages(topic=topic, status=DLQMessageStatus.PENDING)
    assert pending.total == 2

    retried = await repo.get_messages(topic=topic, status=DLQMessageStatus.RETRIED)
    assert retried.total == 1


@pytest.mark.asyncio
async def test_get_dlq_stats(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    topic = unique_id("topic-")

    await create_dlq_doc(unique_id("dlq-1-"), topic, status=DLQMessageStatus.PENDING)
    await create_dlq_doc(unique_id("dlq-2-"), topic, status=DLQMessageStatus.RETRIED)

    stats = await repo.get_dlq_stats()

    assert isinstance(stats.by_status, dict)
    assert isinstance(stats.by_topic, list)
    assert isinstance(stats.by_event_type, list)
    assert stats.age_stats is not None


@pytest.mark.asyncio
async def test_get_topics_summary(repo: DLQRepository, db: Database, unique_id: Callable[[str], str]) -> None:
    topic = unique_id("topic-")

    await create_dlq_doc(unique_id("dlq-1-"), topic, status=DLQMessageStatus.PENDING)
    await create_dlq_doc(unique_id("dlq-2-"), topic, status=DLQMessageStatus.PENDING)
    await create_dlq_doc(unique_id("dlq-3-"), topic, status=DLQMessageStatus.RETRIED)

    summaries = await repo.get_topics_summary()
    topic_summary = next((s for s in summaries if s.topic == topic), None)

    assert topic_summary is not None
    assert topic_summary.total_messages == 3
    assert topic_summary.status_breakdown[DLQMessageStatus.PENDING] == 2
    assert topic_summary.status_breakdown[DLQMessageStatus.RETRIED] == 1


@pytest.mark.asyncio
async def test_retry_messages_batch_not_found(
    repo: DLQRepository, db: Database, unique_id: Callable[[str], str]
) -> None:
    class MockManager:
        async def retry_message_manually(self, event_id: str) -> bool:
            return True

    result = await repo.retry_messages_batch([unique_id("missing-")], MockManager())  # type: ignore[arg-type]
    assert result.total == 1
    assert result.failed == 1
    assert result.successful == 0
    assert result.details[0].status == "failed"
    assert result.details[0].error is not None
    assert "not found" in result.details[0].error.lower()
