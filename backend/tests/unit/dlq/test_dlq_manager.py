from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock

from app.dlq.manager import DLQManager
from app.dlq.models import DLQFields, DLQMessage, DLQMessageStatus, RetryPolicy, RetryStrategy
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.domain.enums.auth import LoginMethod


def make_event():
    return UserLoggedInEvent(user_id="u1", login_method=LoginMethod.PASSWORD, metadata=EventMetadata(service_name="svc", service_version="1"))


@pytest.mark.asyncio
async def test_store_and_update_status_and_filters():
    # Fake db collection
    coll = AsyncMock()
    db = SimpleNamespace(dlq_messages=coll)
    m = DLQManager(database=db)
    # Filters drop message
    m.add_filter(lambda msg: False)
    msg = DLQMessage.from_failed_event(make_event(), "t", "e", "p")
    await m._process_dlq_message(msg)
    coll.update_one.assert_not_awaited()
    # Remove filter; store and schedule
    m._filters.clear()
    await m._store_message(msg)
    coll.update_one.assert_awaited()
    coll.update_one.reset_mock()
    await m._update_message_status(msg.event_id, DLQMessageStatus.SCHEDULED, next_retry_at=datetime.now(timezone.utc))
    assert coll.update_one.await_count == 1


@pytest.mark.asyncio
async def test_retry_policy_paths_and_discard(monkeypatch):
    coll = AsyncMock()
    db = SimpleNamespace(dlq_messages=coll)
    # Default policy manual (no retry) by mapping topic
    pol = RetryPolicy(topic="t", strategy=RetryStrategy.MANUAL, max_retries=0)
    m = DLQManager(database=db)
    m.set_retry_policy("t", pol)
    msg = DLQMessage.from_failed_event(make_event(), "t", "e", "p")
    # Spy discard
    called = {"n": 0}
    async def discard(message, reason):  # noqa: ANN001
        called["n"] += 1
    m._discard_message = discard  # type: ignore[method-assign]
    await m._process_dlq_message(msg)
    assert called["n"] == 1

