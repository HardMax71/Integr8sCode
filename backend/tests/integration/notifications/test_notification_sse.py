import asyncio
import json
from uuid import uuid4
import pytest

from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.services.notification_service import NotificationService
from app.services.sse.redis_bus import SSERedisBus
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.redis]


@pytest.mark.asyncio
async def test_in_app_notification_published_to_sse(scope) -> None:  # type: ignore[valid-type]
    svc: NotificationService = await scope.get(NotificationService)
    bus: SSERedisBus = await scope.get(SSERedisBus)

    user_id = f"notif-user-{uuid4().hex[:8]}"
    # Open subscription before creating notification to catch the publish
    sub = await bus.open_notification_subscription(user_id)

    # Enable IN_APP subscription for the user to allow delivery
    await svc.update_subscription(user_id, NotificationChannel.IN_APP, True)

    # Create notification via service (IN_APP channel triggers SSE publish)
    n = await svc.create_notification(
        user_id=user_id,
        subject="Hello",
        body="World",
        tags=["test"],
        severity=NotificationSeverity.MEDIUM,
        channel=NotificationChannel.IN_APP,
    )

    # Receive published SSE payload
    async def _recv():
        m = await sub.get(timeout=0.5)
        assert m is not None
        return m

    msg = await eventually(_recv, timeout=5.0, interval=0.1)
    # Basic shape assertions
    assert msg.get("subject") == "Hello"
    assert msg.get("body") == "World"
    assert "notification_id" in msg
