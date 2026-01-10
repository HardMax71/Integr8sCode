import pytest
from dishka import AsyncContainer

from app.db.repositories import NotificationRepository
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.domain.notification import DomainNotificationCreate
from app.services.notification_service import NotificationService

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_notification_service_crud_and_subscription(scope: AsyncContainer) -> None:
    svc: NotificationService = await scope.get(NotificationService)
    repo: NotificationRepository = await scope.get(NotificationRepository)

    # Create a notification via repository and then use service to mark/delete
    n = DomainNotificationCreate(user_id="u1", severity=NotificationSeverity.MEDIUM, tags=["x"], channel=NotificationChannel.IN_APP, subject="s", body="b")
    created = await repo.create_notification(n)
    got = await repo.get_notification(created.notification_id, "u1")
    assert got is not None

    # Mark as read through service
    ok = await svc.mark_as_read("u1", created.notification_id)
    assert ok is True

    # Subscriptions via service wrapper calls the repo
    await svc.update_subscription("u1", NotificationChannel.IN_APP, True)
    sub = await repo.get_subscription("u1", NotificationChannel.IN_APP)
    assert sub and sub.enabled is True

    # Delete via service
    assert await svc.delete_notification("u1", created.notification_id) is True
