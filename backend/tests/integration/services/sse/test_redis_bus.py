import asyncio
import json
from typing import Any

import pytest

pytestmark = pytest.mark.integration

from app.domain.enums.events import EventType
from app.schemas_pydantic.sse import RedisNotificationMessage, RedisSSEMessage
from app.services.sse.redis_bus import SSERedisBus


class _DummyEvent:
    def __init__(self, execution_id: str, event_type: EventType, extra: dict[str, Any] | None = None) -> None:
        self.execution_id = execution_id
        self.event_type = event_type
        self._extra = extra or {}

    def model_dump(self, mode: str | None = None) -> dict[str, Any]:  # noqa: ARG002
        return {"execution_id": self.execution_id, **self._extra}


class _FakePubSub:
    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.add(channel)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0.5):  # noqa: ARG002
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
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self._pubsub = _FakePubSub()

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


@pytest.mark.asyncio
async def test_publish_and_subscribe_round_trip() -> None:
    r = _FakeRedis()
    bus = SSERedisBus(r)

    # Subscribe
    sub = await bus.open_subscription("exec-1")
    assert isinstance(sub, object)
    assert "sse:exec:exec-1" in r._pubsub.subscribed

    # Publish event
    evt = _DummyEvent("exec-1", EventType.EXECUTION_COMPLETED, {"status": "completed"})
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
    bus = SSERedisBus(r)
    nsub = await bus.open_notification_subscription("user-1")
    assert "sse:notif:user-1" in r._pubsub.subscribed

    notif = RedisNotificationMessage(
        notification_id="n1",
        severity="low",
        status="pending",
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
