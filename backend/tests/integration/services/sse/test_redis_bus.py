import asyncio
import logging
from typing import Any, ClassVar, cast

import pytest
import redis.asyncio as redis_async

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.infrastructure.kafka.events import BaseEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.schemas_pydantic.sse import RedisNotificationMessage, RedisSSEMessage
from app.services.sse.redis_bus import SSERedisBus

pytestmark = pytest.mark.integration

_test_logger = logging.getLogger("test.services.sse.redis_bus")


class _DummyEvent(BaseEvent):
    """Dummy event for testing."""
    execution_id: str = ""
    status: str | None = None
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS

    def model_dump(self, **kwargs: object) -> dict[str, Any]:
        return {"execution_id": self.execution_id, "status": self.status}


class _FakePubSub:
    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.add(channel)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0.5) -> dict[str, Any] | None:
        try:
            msg = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return msg
        except asyncio.TimeoutError:
            return None

    async def push(self, channel: str, payload: str | bytes) -> None:
        self._queue.put_nowait({"type": "message", "channel": channel, "data": payload})

    async def unsubscribe(self, channel: str) -> None:
        self.subscribed.discard(channel)

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    """Fake Redis for testing - used in place of real Redis.

    Note: SSERedisBus uses duck-typing so this works without inheritance.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self._pubsub = _FakePubSub()

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


def _make_metadata() -> AvroEventMetadata:
    return AvroEventMetadata(service_name="test", service_version="1.0")


@pytest.mark.asyncio
async def test_publish_and_subscribe_round_trip() -> None:
    r = _FakeRedis()
    bus = SSERedisBus(cast(redis_async.Redis, r), logger=_test_logger)

    # Subscribe
    sub = await bus.open_subscription("exec-1")
    assert isinstance(sub, object)
    assert "sse:exec:exec-1" in r._pubsub.subscribed

    # Publish event
    evt = _DummyEvent(
        event_type=EventType.EXECUTION_COMPLETED,
        metadata=_make_metadata(),
        execution_id="exec-1",
        status="completed"
    )
    await bus.publish_event("exec-1", evt)
    assert r.published, "nothing published"
    ch, payload = r.published[-1]
    assert ch.endswith("exec-1")
    # Push to pubsub and read from subscription
    await r._pubsub.push(ch, payload)
    msg = await sub.get(RedisSSEMessage)
    assert msg and msg.event_type == EventType.EXECUTION_COMPLETED
    assert msg.execution_id == "exec-1"

    # Non-message / invalid JSON paths
    await r._pubsub.push(ch, b"not-json")
    assert await sub.get(RedisSSEMessage) is None

    # Close
    await sub.close()
    assert "sse:exec:exec-1" not in r._pubsub.subscribed and r._pubsub.closed is True


@pytest.mark.asyncio
async def test_notifications_channels() -> None:
    r = _FakeRedis()
    bus = SSERedisBus(cast(redis_async.Redis, r), logger=_test_logger)
    nsub = await bus.open_notification_subscription("user-1")
    assert "sse:notif:user-1" in r._pubsub.subscribed

    notif = RedisNotificationMessage(
        notification_id="n1",
        severity=NotificationSeverity.LOW,
        status=NotificationStatus.PENDING,
        tags=[],
        subject="test",
        body="body",
        action_url="",
        created_at="2025-01-01T00:00:00Z",
    )
    await bus.publish_notification("user-1", notif)
    ch, payload = r.published[-1]
    assert ch.endswith("user-1")
    await r._pubsub.push(ch, payload)
    got = await nsub.get(RedisNotificationMessage)
    assert got is not None
    assert got.notification_id == "n1"

    await nsub.close()
