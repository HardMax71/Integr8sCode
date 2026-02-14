import asyncio
from uuid import uuid4

import pytest
from app.domain.enums import NotificationChannel, NotificationSeverity
from app.domain.notification import DomainSubscriptionUpdate
from app.domain.sse import RedisNotificationMessage
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.redis]


@pytest.mark.asyncio
async def test_in_app_notification_published_to_sse(scope: AsyncContainer) -> None:
    svc: NotificationService = await scope.get(NotificationService)
    bus: SSERedisBus = await scope.get(SSERedisBus)

    user_id = f"notif-user-{uuid4().hex[:8]}"
    # Open subscription before creating notification to catch the publish
    sub = await bus.open_notification_subscription(user_id)

    # Enable IN_APP subscription for the user to allow delivery
    await svc.update_subscription(user_id, NotificationChannel.IN_APP, DomainSubscriptionUpdate(enabled=True))

    # Create notification via service (IN_APP channel triggers SSE publish)
    # Delivery is now awaited synchronously - message in Redis immediately
    await svc.create_notification(
        user_id=user_id,
        subject="Hello",
        body="World",
        tags=["test"],
        action_url="/api/v1/notifications",
        severity=NotificationSeverity.MEDIUM,
        channel=NotificationChannel.IN_APP,
    )

    # Await the subscription directly - true async, no polling
    msg = await asyncio.wait_for(sub.get(RedisNotificationMessage), timeout=5.0)
    # Basic shape assertions
    assert msg is not None
    assert msg.subject == "Hello"
    assert msg.body == "World"
    assert msg.notification_id
