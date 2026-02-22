from __future__ import annotations

import asyncio
import structlog
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, cast

import pytest
import redis.asyncio as redis_async
from app.domain.enums import EventType, NotificationSeverity, NotificationStatus
from app.domain.events import EventMetadata, ExecutionCompletedEvent
from app.domain.sse import RedisNotificationMessage, SSEExecutionEventData
from app.services.sse import SSERedisBus
from app.services.sse.redis_bus import _notif_msg_adapter, _sse_event_adapter

pytestmark = pytest.mark.e2e

_test_logger = structlog.get_logger("test.services.sse.redis_bus")


class _FakePubSub:
    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.closed = False

    async def __aenter__(self) -> _FakePubSub:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def subscribe(self, channel: str) -> None:
        self.subscribed.add(channel)

    async def push(self, channel: str, payload: str | bytes) -> None:
        self._queue.put_nowait({"type": "message", "channel": channel, "data": payload})

    async def listen(self) -> AsyncGenerator[dict[str, Any], None]:
        while True:
            msg = await self._queue.get()
            if msg is None:
                return
            yield msg

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


def _make_metadata() -> EventMetadata:
    return EventMetadata(service_name="test", service_version="1.0")


@pytest.mark.asyncio
async def test_publish_and_subscribe_round_trip() -> None:
    r = _FakeRedis()
    bus = SSERedisBus(cast(redis_async.Redis, r), logger=_test_logger)

    # Publish event
    evt = ExecutionCompletedEvent(
        execution_id="exec-1",
        exit_code=0,
        stdout="",
        stderr="",
        metadata=_make_metadata(),
    )
    await bus.publish_event("exec-1", evt)
    assert r.published, "nothing published"
    ch, payload = r.published[-1]
    assert ch.endswith("exec-1")

    # Push message into fake pubsub queue before iterating (subscription is lazy)
    await r._pubsub.push(ch, payload)

    # listen_execution is an async generator — no await needed
    messages = bus.listen_execution("exec-1")
    msg = await asyncio.wait_for(messages.__anext__(), timeout=2.0)
    # Subscription happened inside __anext__
    assert "sse:exec:exec-1" in r._pubsub.subscribed
    assert msg.event_type == EventType.EXECUTION_COMPLETED
    assert msg.execution_id == "exec-1"

    # A second valid message passes through cleanly
    good_payload = _sse_event_adapter.dump_json(
        _sse_event_adapter.validate_python({"event_type": EventType.EXECUTION_COMPLETED, "execution_id": "exec-1"})
    )
    await r._pubsub.push(ch, good_payload)
    msg2 = await asyncio.wait_for(messages.__anext__(), timeout=2.0)
    assert msg2.event_type == EventType.EXECUTION_COMPLETED

    # Close — aclose() on the generator triggers __aexit__ on the pubsub context
    await messages.aclose()
    assert r._pubsub.closed is True


@pytest.mark.asyncio
async def test_notifications_channels() -> None:
    r = _FakeRedis()
    bus = SSERedisBus(cast(redis_async.Redis, r), logger=_test_logger)

    notif = RedisNotificationMessage(
        notification_id="n1",
        severity=NotificationSeverity.LOW,
        status=NotificationStatus.PENDING,
        tags=[],
        subject="test",
        body="body",
        action_url="",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    await bus.publish_notification("user-1", notif)
    ch, payload = r.published[-1]
    assert ch.endswith("user-1")

    # Push message before iterating (subscription is lazy)
    await r._pubsub.push(ch, payload)

    messages = bus.listen_notifications("user-1")
    got = await asyncio.wait_for(messages.__anext__(), timeout=2.0)
    # Subscription happened inside __anext__
    assert "sse:notif:user-1" in r._pubsub.subscribed
    assert got.notification_id == "n1"

    await messages.aclose()
    assert r._pubsub.closed is True
