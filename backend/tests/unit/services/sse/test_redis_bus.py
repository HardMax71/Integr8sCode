import asyncio
import logging
from typing import Any, TypeVar

import pytest
from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.domain.execution.models import ResourceUsageDomain
from app.infrastructure.kafka.events.execution import ExecutionCompletedEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.schemas_pydantic.sse import RedisNotificationMessage, RedisSSEMessage
from app.services.sse.redis_bus import SSERedisBus
from fakeredis import FakeAsyncRedis

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.redis_bus")
_T = TypeVar("_T")


def _make_completed_event(execution_id: str) -> ExecutionCompletedEvent:
    return ExecutionCompletedEvent(
        execution_id=execution_id,
        exit_code=0,
        stdout="ok",
        stderr="",
        resource_usage=ResourceUsageDomain(),
        metadata=AvroEventMetadata(service_name="test", service_version="1.0"),
    )


async def _wait_for_message(sub: Any, model: type[_T], timeout: float = 1.0) -> _T:
    """Wait for a non-None message with explicit timeout."""
    async with asyncio.timeout(timeout):
        while True:
            msg: _T | None = await sub.get(model)
            if msg is not None:
                return msg
            await asyncio.sleep(0.01)  # Yield, not timing dependency


@pytest.mark.asyncio
async def test_publish_and_subscribe_round_trip() -> None:
    redis = FakeAsyncRedis()
    bus = SSERedisBus(redis, logger=_test_logger)

    sub = await bus.open_subscription("exec-1")
    evt = _make_completed_event("exec-1")

    async def publish_later() -> None:
        await asyncio.sleep(0.05)
        await bus.publish_event("exec-1", evt)

    pub_task = asyncio.create_task(publish_later())

    # Wait with explicit timeout instead of polling loop
    msg = await _wait_for_message(sub, RedisSSEMessage)
    await pub_task

    assert msg.execution_id == "exec-1"

    # Invalid JSON should be skipped - verify by sending valid message after invalid
    # and confirming we receive only the valid one (no crash, no stale data)
    await redis.publish("sse:exec:exec-1", "not-json")
    evt2 = _make_completed_event("exec-1")
    await bus.publish_event("exec-1", evt2)

    # Should receive the valid message, proving invalid JSON was skipped
    msg2 = await _wait_for_message(sub, RedisSSEMessage)
    assert msg2.execution_id == "exec-1"

    await sub.close()
    await redis.aclose()


@pytest.mark.asyncio
async def test_notifications_channels() -> None:
    redis = FakeAsyncRedis()
    bus = SSERedisBus(redis, logger=_test_logger)

    nsub = await bus.open_notification_subscription("user-1")

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

    async def publish_later() -> None:
        await asyncio.sleep(0.05)
        await bus.publish_notification("user-1", notif)

    pub_task = asyncio.create_task(publish_later())

    # Wait with explicit timeout instead of polling loop
    got = await _wait_for_message(nsub, RedisNotificationMessage)
    await pub_task

    assert got.notification_id == "n1"

    await nsub.close()
    await redis.aclose()
