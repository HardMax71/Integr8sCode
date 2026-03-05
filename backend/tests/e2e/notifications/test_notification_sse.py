import asyncio
from uuid import uuid4

import pytest
from app.domain.enums import NotificationChannel, NotificationSeverity
from app.domain.notification import DomainSubscriptionUpdate
from app.domain.sse import DomainNotificationSSEPayload
from app.services.notification_service import NotificationService
from app.services.sse import SSEService
from app.services.sse.sse_service import _notif_adapter
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.redis]


@pytest.mark.asyncio
async def test_in_app_notification_published_to_sse(scope: AsyncContainer) -> None:
    svc: NotificationService = await scope.get(NotificationService)
    sse: SSEService = await scope.get(SSEService)

    user_id = f"notif-user-{uuid4().hex[:8]}"

    # Enable IN_APP subscription for the user to allow delivery
    await svc.update_subscription(user_id, NotificationChannel.IN_APP, DomainSubscriptionUpdate(enabled=True))

    await svc.create_notification(
        user_id=user_id,
        subject="Hello",
        body="World",
        tags=["test"],
        action_url="/api/v1/notifications",
        severity=NotificationSeverity.MEDIUM,
        channel=NotificationChannel.IN_APP,
    )

    # Read back from stream
    gen = sse._poll_stream(f"sse:notif:{user_id}", _notif_adapter)
    msg: DomainNotificationSSEPayload = await asyncio.wait_for(gen.__anext__(), timeout=5.0)

    assert msg is not None
    assert msg.subject == "Hello"
    assert msg.body == "World"
    assert msg.notification_id
