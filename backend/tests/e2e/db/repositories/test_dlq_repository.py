import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest

from app.db.docs import DLQMessageDocument
from app.db.repositories import DLQRepository
from app.dlq import DLQMessageStatus
from app.domain.enums import EventType, LoginMethod
from app.domain.events import EventMetadata, UserLoggedInEvent

pytestmark = pytest.mark.e2e


@pytest.fixture
async def dlq_docs() -> AsyncIterator[list[str]]:
    """Three DLQ rows on topics t1 and t2; they go when the test ends, so the DLQ size job stops counting them."""
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
    yield event_ids
    await DLQMessageDocument.find({"event.event_id": {"$in": event_ids}}).delete()


@pytest.fixture
async def logged_in_event() -> AsyncIterator[UserLoggedInEvent]:
    """The event the test dead-letters for two groups; its rows go when the test ends."""
    event = UserLoggedInEvent(
        user_id="u1",
        login_method=LoginMethod.PASSWORD,
        metadata=EventMetadata(service_name="svc", service_version="1", user_id="u1"),
    )
    yield event
    await DLQMessageDocument.find({"event.event_id": event.event_id}).delete()


async def test_list_get_and_updates(dlq_repository: DLQRepository, dlq_docs: list[str]) -> None:
    res = await dlq_repository.get_messages(limit=2)
    assert res.total >= 3 and len(res.messages) <= 2
    topics = await dlq_repository.get_topics_summary()
    assert any(t.topic == "t1" for t in topics)


async def test_each_consumer_group_keeps_its_own_row(
    dlq_repository: DLQRepository, logged_in_event: UserLoggedInEvent
) -> None:
    for group, error in [("group-a", "a failed"), ("group-b", "b failed"), ("group-a", "a failed again")]:
        await dlq_repository.save_message(
            DLQMessageDocument(event=logged_in_event, original_topic="t1", consumer_group=group, error=error)
        )

    docs = await DLQMessageDocument.find({"event.event_id": logged_in_event.event_id}).sort("consumer_group").to_list()
    assert [(d.consumer_group, d.error) for d in docs] == [("group-a", "a failed again"), ("group-b", "b failed")]
