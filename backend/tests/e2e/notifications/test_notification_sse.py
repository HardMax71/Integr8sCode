import asyncio
from uuid import uuid4

import pytest
from app.domain.enums import NotificationChannel, NotificationSeverity
from app.domain.notification import DomainSubscriptionUpdate
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.redis]


@pytest.mark.asyncio
async def test_in_app_notification_published_to_sse(scope: AsyncContainer) -> None:
    svc: NotificationService = await scope.get(NotificationService)
    bus: SSERedisBus = await scope.get(SSERedisBus)

    user_id = f"notif-user-{uuid4().hex[:8]}"

    # Enable IN_APP subscription for the user to allow delivery
    await svc.update_subscription(user_id, NotificationChannel.IN_APP, DomainSubscriptionUpdate(enabled=True))

    # Start generator (subscription happens on first __anext__) and publish concurrently.
    # By the time create_notification fires, the subscribe is already established.
    messages = bus.listen_notifications(user_id)
    pub_task = asyncio.create_task(svc.create_notification(
        user_id=user_id,
        subject="Hello",
        body="World",
        tags=["test"],
        action_url="/api/v1/notifications",
        severity=NotificationSeverity.MEDIUM,
        channel=NotificationChannel.IN_APP,
    ))
    msg = await asyncio.wait_for(messages.__anext__(), timeout=5.0)
    await pub_task
    await messages.aclose()

    assert msg is not None
    assert msg.subject == "Hello"
    assert msg.body == "World"
    assert msg.notification_id
