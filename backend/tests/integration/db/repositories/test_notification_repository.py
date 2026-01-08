"""Integration tests for NotificationRepository."""
import logging
from collections.abc import Callable

import pytest
from app.db.repositories.notification_repository import NotificationRepository
from app.domain.enums.notification import NotificationChannel, NotificationSeverity, NotificationStatus
from app.domain.notification import (
    DomainNotificationCreate,
    DomainNotificationUpdate,
    DomainSubscriptionUpdate,
)

_test_logger = logging.getLogger("test.db.repositories.notification_repository")

pytestmark = pytest.mark.integration


def _make_notification_create(
    user_id: str,
    subject: str = "Test Notification",
    body: str = "Test message content",
    severity: NotificationSeverity = NotificationSeverity.MEDIUM,
    tags: list[str] | None = None,
) -> DomainNotificationCreate:
    """Factory for notification create data."""
    return DomainNotificationCreate(
        user_id=user_id,
        channel=NotificationChannel.IN_APP,
        subject=subject,
        body=body,
        severity=severity,
        tags=tags or ["test"],
    )


@pytest.mark.asyncio
async def test_create_and_get_notification(unique_id: Callable[[str], str]) -> None:
    """Create notification and retrieve by ID."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    create_data = _make_notification_create(user_id)
    created = await repo.create_notification(create_data)

    assert created.notification_id
    assert created.user_id == user_id
    assert created.status == NotificationStatus.PENDING

    # Retrieve
    retrieved = await repo.get_notification(created.notification_id, user_id)
    assert retrieved is not None
    assert retrieved.subject == "Test Notification"


@pytest.mark.asyncio
async def test_get_notification_wrong_user(unique_id: Callable[[str], str]) -> None:
    """Cannot get notification belonging to another user."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    created = await repo.create_notification(_make_notification_create(user_id))

    # Try to get with wrong user
    result = await repo.get_notification(created.notification_id, unique_id("other-user-"))
    assert result is None


@pytest.mark.asyncio
async def test_update_notification(unique_id: Callable[[str], str]) -> None:
    """Update notification fields."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    created = await repo.create_notification(_make_notification_create(user_id))

    # Update
    update = DomainNotificationUpdate(status=NotificationStatus.DELIVERED)
    success = await repo.update_notification(created.notification_id, user_id, update)
    assert success is True

    # Verify
    updated = await repo.get_notification(created.notification_id, user_id)
    assert updated is not None
    assert updated.status == NotificationStatus.DELIVERED


@pytest.mark.asyncio
async def test_update_notification_not_found(unique_id: Callable[[str], str]) -> None:
    """Update returns False for non-existent notification."""
    repo = NotificationRepository(logger=_test_logger)
    update = DomainNotificationUpdate(status=NotificationStatus.DELIVERED)
    result = await repo.update_notification(unique_id("notif-"), unique_id("user-"), update)
    assert result is False


@pytest.mark.asyncio
async def test_mark_as_read(unique_id: Callable[[str], str]) -> None:
    """Mark notification as read."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    created = await repo.create_notification(_make_notification_create(user_id))
    # Set to delivered first
    await repo.update_notification(
        created.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.DELIVERED)
    )

    success = await repo.mark_as_read(created.notification_id, user_id)
    assert success is True

    notif = await repo.get_notification(created.notification_id, user_id)
    assert notif is not None
    assert notif.status == NotificationStatus.READ
    assert notif.read_at is not None


@pytest.mark.asyncio
async def test_mark_all_as_read(unique_id: Callable[[str], str]) -> None:
    """Mark all user notifications as read."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    # Create multiple notifications and set to delivered
    for _ in range(3):
        created = await repo.create_notification(_make_notification_create(user_id))
        await repo.update_notification(
            created.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.DELIVERED)
        )

    count = await repo.mark_all_as_read(user_id)
    assert count >= 3


@pytest.mark.asyncio
async def test_delete_notification(unique_id: Callable[[str], str]) -> None:
    """Delete notification."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    created = await repo.create_notification(_make_notification_create(user_id))

    success = await repo.delete_notification(created.notification_id, user_id)
    assert success is True

    # Verify deleted
    assert await repo.get_notification(created.notification_id, user_id) is None


@pytest.mark.asyncio
async def test_list_notifications_with_filters(unique_id: Callable[[str], str]) -> None:
    """List notifications with various filters."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    # Create notifications with different tags
    n1 = await repo.create_notification(_make_notification_create(user_id, tags=["alert", "critical"]))
    await repo.update_notification(n1.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.DELIVERED))

    await repo.create_notification(_make_notification_create(user_id, tags=["info"]))

    n3 = await repo.create_notification(_make_notification_create(user_id, tags=["alert", "warning"]))
    await repo.update_notification(n3.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.DELIVERED))

    # List all
    all_notifs = await repo.list_notifications(user_id)
    assert len(all_notifs) >= 3

    # Filter by status
    delivered = await repo.list_notifications(user_id, status=NotificationStatus.DELIVERED)
    assert len(delivered) >= 2

    # Filter by include_tags
    alerts = await repo.list_notifications(user_id, include_tags=["alert"])
    assert len(alerts) >= 2


@pytest.mark.asyncio
async def test_count_and_unread_count(unique_id: Callable[[str], str]) -> None:
    """Count notifications and unread count."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    n1 = await repo.create_notification(_make_notification_create(user_id))
    await repo.update_notification(n1.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.DELIVERED))

    n2 = await repo.create_notification(_make_notification_create(user_id))
    await repo.update_notification(n2.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.READ))

    total = await repo.count_notifications(user_id)
    assert total >= 2

    unread = await repo.get_unread_count(user_id)
    assert unread >= 1


@pytest.mark.asyncio
async def test_try_claim_pending(unique_id: Callable[[str], str]) -> None:
    """Claim pending notification for processing."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    created = await repo.create_notification(_make_notification_create(user_id))

    claimed = await repo.try_claim_pending(created.notification_id)
    assert claimed is True

    # Verify status changed
    notif = await repo.get_notification(created.notification_id, user_id)
    assert notif is not None
    assert notif.status == NotificationStatus.SENDING


@pytest.mark.asyncio
async def test_try_claim_already_claimed(unique_id: Callable[[str], str]) -> None:
    """Cannot claim already claimed notification."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    created = await repo.create_notification(_make_notification_create(user_id))
    await repo.update_notification(
        created.notification_id, user_id, DomainNotificationUpdate(status=NotificationStatus.SENDING)
    )

    claimed = await repo.try_claim_pending(created.notification_id)
    assert claimed is False


@pytest.mark.asyncio
async def test_find_pending_notifications(unique_id: Callable[[str], str]) -> None:
    """Find pending notifications ready for processing."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    # Create pending notifications
    for _ in range(3):
        await repo.create_notification(_make_notification_create(user_id))

    pending = await repo.find_pending_notifications(batch_size=10)
    assert len(pending) >= 3


@pytest.mark.asyncio
async def test_subscription_upsert_and_get(unique_id: Callable[[str], str]) -> None:
    """Create and update subscription."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    # Create
    update = DomainSubscriptionUpdate(enabled=True)
    sub = await repo.upsert_subscription(user_id, NotificationChannel.IN_APP, update)
    assert sub.enabled is True

    # Update
    update2 = DomainSubscriptionUpdate(enabled=False)
    sub2 = await repo.upsert_subscription(user_id, NotificationChannel.IN_APP, update2)
    assert sub2.enabled is False

    # Get
    retrieved = await repo.get_subscription(user_id, NotificationChannel.IN_APP)
    assert retrieved is not None
    assert retrieved.enabled is False


@pytest.mark.asyncio
async def test_get_all_subscriptions(unique_id: Callable[[str], str]) -> None:
    """Get all channel subscriptions with defaults."""
    repo = NotificationRepository(logger=_test_logger)
    user_id = unique_id("user-")

    # Set one subscription
    await repo.upsert_subscription(
        user_id, NotificationChannel.WEBHOOK, DomainSubscriptionUpdate(enabled=False)
    )

    subs = await repo.get_all_subscriptions(user_id)

    # Should have all channels
    assert len(subs) == len(NotificationChannel)
    # Explicit one should be disabled
    assert subs[NotificationChannel.WEBHOOK].enabled is False
    # Default ones should be enabled
    assert subs[NotificationChannel.IN_APP].enabled is True
