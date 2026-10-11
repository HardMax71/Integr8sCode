import uuid
from datetime import datetime, timezone

import pytest
from dishka import AsyncContainer

from app.db.docs import DLQMessageDocument
from app.db.repositories import DLQRepository
from app.dlq import DLQMessage, DLQMessageStatus
from app.domain.enums import EventType, LoginMethod
from app.domain.events import EventMetadata, UserLoggedInEvent

pytestmark = pytest.mark.e2e


@pytest.fixture()
async def repo(scope: AsyncContainer) -> DLQRepository:
    return await scope.get(DLQRepository)


async def insert_test_dlq_docs() -> list[str]:
    """Insert test DLQ documents using Beanie and return their event ids."""
    now = datetime.now(timezone.utc)
    event_ids = [f"dlq-{uuid.uuid4().hex}" for _ in range(3)]

    docs = [
        DLQMessageDocument(
            event={
                "event_id": event_ids[0],
                "event_type": EventType.USER_LOGGED_IN,
                "metadata": {"service_name": "svc", "service_version": "1", "user_id": "u1"},
                "user_id": "u1",
                "login_method": "password",
            },
            original_topic="t1",
            error="err",
            retry_count=0,
            failed_at=now,
            status=DLQMessageStatus.PENDING,
            producer_id="p1",
        ),
        DLQMessageDocument(
            event={
                "event_id": event_ids[1],
                "event_type": EventType.USER_LOGGED_IN,
                "metadata": {"service_name": "svc", "service_version": "1", "user_id": "u1"},
                "user_id": "u1",
                "login_method": "password",
            },
            original_topic="t1",
            error="err",
            retry_count=0,
            failed_at=now,
            status=DLQMessageStatus.RETRIED,
            producer_id="p1",
        ),
        DLQMessageDocument(
            event={
                "event_id": event_ids[2],
                "event_type": EventType.EXECUTION_STARTED,
                "metadata": {"service_name": "svc", "service_version": "1", "user_id": "u1"},
                "execution_id": "x1",
                "pod_name": "p1",
            },
            original_topic="t2",
            error="err",
            retry_count=0,
            failed_at=now,
            status=DLQMessageStatus.PENDING,
            producer_id="p1",
        ),
    ]

    for doc in docs:
        await doc.insert()
    return event_ids


@pytest.mark.asyncio
async def test_list_get_and_updates(repo: DLQRepository) -> None:
    await insert_test_dlq_docs()

    res = await repo.get_messages(limit=2)
    assert res.total >= 3 and len(res.messages) <= 2
    topics = await repo.get_topics_summary()
    assert any(t.topic == "t1" for t in topics)


@pytest.mark.asyncio
async def test_each_consumer_group_keeps_its_own_row(repo: DLQRepository) -> None:
    event = UserLoggedInEvent(
        user_id="u1",
        login_method=LoginMethod.PASSWORD,
        metadata=EventMetadata(service_name="svc", service_version="1", user_id="u1"),
    )
    for group, error in [("group-a", "a failed"), ("group-b", "b failed"), ("group-a", "a failed again")]:
        await repo.save_message(DLQMessage(event=event, original_topic="t1", consumer_group=group, error=error))

    docs = await DLQMessageDocument.find({"event.event_id": event.event_id}).sort("consumer_group").to_list()
    assert [(d.consumer_group, d.error) for d in docs] == [("group-a", "a failed again"), ("group-b", "b failed")]
