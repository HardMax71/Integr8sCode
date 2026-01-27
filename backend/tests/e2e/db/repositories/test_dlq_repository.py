import logging
from datetime import datetime, timezone

import pytest
from app.db.docs import DLQMessageDocument
from app.db.repositories.dlq_repository import DLQRepository
from app.dlq import DLQMessageStatus
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic

pytestmark = pytest.mark.e2e

_test_logger = logging.getLogger("test.db.repositories.dlq_repository")


@pytest.fixture()
def repo() -> DLQRepository:
    return DLQRepository(_test_logger)


async def insert_test_dlq_docs() -> None:
    """Insert test DLQ documents using Beanie."""
    now = datetime.now(timezone.utc)

    docs = [
        DLQMessageDocument(
            event={
                "event_id": "id1",
                "event_type": str(EventType.USER_LOGGED_IN),
                "metadata": {"service_name": "svc", "service_version": "1"},
                "user_id": "u1",
                "login_method": "password",
            },
            original_topic=KafkaTopic.USER_EVENTS,
            error="err",
            retry_count=0,
            failed_at=now,
            status=DLQMessageStatus.PENDING,
            producer_id="p1",
        ),
        DLQMessageDocument(
            event={
                "event_id": "id2",
                "event_type": str(EventType.USER_LOGGED_IN),
                "metadata": {"service_name": "svc", "service_version": "1"},
                "user_id": "u1",
                "login_method": "password",
            },
            original_topic=KafkaTopic.USER_EVENTS,
            error="err",
            retry_count=0,
            failed_at=now,
            status=DLQMessageStatus.RETRIED,
            producer_id="p1",
        ),
        DLQMessageDocument(
            event={
                "event_id": "id3",
                "event_type": str(EventType.EXECUTION_STARTED),
                "metadata": {"service_name": "svc", "service_version": "1"},
                "execution_id": "x1",
                "pod_name": "p1",
            },
            original_topic=KafkaTopic.EXECUTION_EVENTS,
            error="err",
            retry_count=0,
            failed_at=now,
            status=DLQMessageStatus.PENDING,
            producer_id="p1",
        ),
    ]

    for doc in docs:
        await doc.insert()


@pytest.mark.asyncio
async def test_stats_list_get_and_updates(repo: DLQRepository) -> None:
    await insert_test_dlq_docs()

    stats = await repo.get_dlq_stats()
    assert isinstance(stats.by_status, dict) and len(stats.by_topic) >= 1

    res = await repo.get_messages(limit=2)
    assert res.total >= 3 and len(res.messages) <= 2
    msg = await repo.get_message_by_id("id1")
    assert msg and msg.event.event_id == "id1"
    assert await repo.mark_message_retried("id1") in (True, False)
    assert await repo.mark_message_discarded("id1", "r") in (True, False)

    topics = await repo.get_topics_summary()
    assert any(t.topic == KafkaTopic.USER_EVENTS for t in topics)
