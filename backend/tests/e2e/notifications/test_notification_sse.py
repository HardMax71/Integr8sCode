import asyncio
from contextlib import aclosing
from uuid import uuid4

import pytest
import redis.asyncio as redis

from app.domain.enums import NotificationChannel, NotificationSeverity
from app.domain.notification import DomainSubscriptionUpdate
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus

pytestmark = [pytest.mark.e2e]


async def test_in_app_notification_published_to_sse(
    redis_client: redis.Redis, notification_service: NotificationService, sse_redis_bus: SSERedisBus
) -> None:

    user_id = f"notif-user-{uuid4().hex[:8]}"

    # Enable IN_APP subscription for the user to allow delivery
    await notification_service.update_subscription(
        user_id, NotificationChannel.IN_APP, DomainSubscriptionUpdate(enabled=True)
    )

    async with aclosing(sse_redis_bus.listen_notifications(user_id)) as messages, asyncio.timeout(5.0):
        async with asyncio.TaskGroup() as tasks:
            next_message = tasks.create_task(messages.__anext__())
            while (await redis_client.pubsub_numsub(f"sse:notif:{user_id}"))[0][1] == 0:
                await asyncio.sleep(0.01)
            await notification_service.create_notification(
                user_id=user_id,
                subject="Hello",
                body="World",
                tags=["test"],
                action_url="/api/v1/notifications",
                severity=NotificationSeverity.MEDIUM,
                channel=NotificationChannel.IN_APP,
            )
    msg = next_message.result()

    assert msg.subject == "Hello"
    assert msg.body == "World"
    assert msg.notification_id
