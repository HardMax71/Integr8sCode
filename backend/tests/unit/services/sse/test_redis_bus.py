import asyncio
import logging

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


def _make_completed_event(execution_id: str) -> ExecutionCompletedEvent:
    return ExecutionCompletedEvent(
        execution_id=execution_id,
        exit_code=0,
        stdout="ok",
        stderr="",
        resource_usage=ResourceUsageDomain(),
        metadata=AvroEventMetadata(service_name="test", service_version="1.0"),
    )


@pytest.mark.asyncio
async def test_publish_and_subscribe_round_trip() -> None:
    redis = FakeAsyncRedis()
    bus = SSERedisBus(redis, logger=_test_logger)

    # Subscribe in background to receive published messages
    sub = await bus.open_subscription("exec-1")

    # Publish event
    evt = _make_completed_event("exec-1")

    async def publish_later() -> None:
        await asyncio.sleep(0.05)
        await bus.publish_event("exec-1", evt)

    pub_task = asyncio.create_task(publish_later())

    # Wait for message
    msg = None
    for _ in range(20):
        msg = await sub.get(RedisSSEMessage)
        if msg:
            break
        await asyncio.sleep(0.05)

    await pub_task
    assert msg is not None
    assert msg.execution_id == "exec-1"

    # Invalid JSON should return None
    await redis.publish("sse:exec:exec-1", "not-json")
    await asyncio.sleep(0.05)
    assert await sub.get(RedisSSEMessage) is None

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

    # Wait for message
    got = None
    for _ in range(20):
        got = await nsub.get(RedisNotificationMessage)
        if got:
            break
        await asyncio.sleep(0.05)

    await pub_task
    assert got is not None
    assert got.notification_id == "n1"

    await nsub.close()
    await redis.aclose()
