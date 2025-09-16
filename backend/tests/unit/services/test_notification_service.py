import pytest

from app.db.repositories import NotificationRepository
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.domain.notification import DomainNotification
from app.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_notification_service_crud_and_subscription(scope) -> None:  # type: ignore[valid-type]
    svc: NotificationService = await scope.get(NotificationService)
    repo: NotificationRepository = await scope.get(NotificationRepository)

    # Create a notification via repository and then use service to mark/delete
    n = DomainNotification(user_id="u1", severity=NotificationSeverity.MEDIUM, tags=["x"], channel=NotificationChannel.IN_APP, subject="s", body="b")
    _nid = await repo.create_notification(n)
    got = await repo.get_notification(n.notification_id, "u1")
    assert got is not None

    # Mark as read through service
    ok = await svc.mark_as_read("u1", got.notification_id)
    assert ok is True

    # Subscriptions via service wrapper calls the repo
    await svc.update_subscription("u1", NotificationChannel.IN_APP, True)
    sub = await repo.get_subscription("u1", NotificationChannel.IN_APP)
    assert sub and sub.enabled is True

    # Delete via service
    assert await svc.delete_notification("u1", got.notification_id) is True
