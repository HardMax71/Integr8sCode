from collections.abc import Callable

import backoff
import pytest
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.schemas_pydantic.sse import RedisNotificationMessage
from app.services.notification_service import NotificationService
from app.services.sse.redis_bus import SSERedisBus
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.redis]


@pytest.mark.asyncio
async def test_in_app_notification_published_to_sse(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: NotificationService = await scope.get(NotificationService)
    bus: SSERedisBus = await scope.get(SSERedisBus)

    user_id = unique_id("notif-user-")
    # Open subscription before creating notification to catch the publish
    sub = await bus.open_notification_subscription(user_id)

    # Enable IN_APP subscription for the user to allow delivery
    await svc.update_subscription(user_id, NotificationChannel.IN_APP, True)

    # Create notification via service (IN_APP channel triggers SSE publish)
    await svc.create_notification(
        user_id=user_id,
        subject="Hello",
        body="World",
        tags=["test"],
        severity=NotificationSeverity.MEDIUM,
        channel=NotificationChannel.IN_APP,
    )

    # Receive published SSE payload
    msg: RedisNotificationMessage | None = None

    @backoff.on_exception(backoff.constant, AssertionError, max_time=5.0, interval=0.1)
    async def _wait_recv() -> None:
        nonlocal msg
        m = await sub.get(RedisNotificationMessage)
        assert m is not None
        msg = m

    await _wait_recv()
    assert msg is not None
    # Basic shape assertions
    assert msg.subject == "Hello"
    assert msg.body == "World"
    assert msg.notification_id
