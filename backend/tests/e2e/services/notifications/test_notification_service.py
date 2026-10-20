import uuid

import pytest

from app.db.repositories import NotificationRepository
from app.domain.enums import NotificationChannel, NotificationSeverity, NotificationStatus
from app.domain.notification import (
    NotificationNotFoundError,
    NotificationValidationError,
    SubscriptionChanges,
)
from app.services.notification_service import NotificationService

pytestmark = [pytest.mark.e2e]


_TEST_ACTION_URL = "/api/v1/notifications"


def _unique_user_id() -> str:
    return f"notif_user_{uuid.uuid4().hex[:8]}"


class TestCreateNotification:
    """Tests for create_notification method."""

    async def test_create_notification_basic(self, notification_service: NotificationService) -> None:
        """Create basic in-app notification."""
        user_id = _unique_user_id()

        notification = await notification_service.create_notification(
            user_id=user_id,
            subject="Test Subject",
            body="Test body content",
            tags=["test", "basic"],
            action_url=_TEST_ACTION_URL,
            severity=NotificationSeverity.MEDIUM,
            channel=NotificationChannel.IN_APP,
        )

        assert notification.notification_id is not None
        assert notification.user_id == user_id
        assert notification.subject == "Test Subject"
        assert notification.body == "Test body content"
        assert notification.severity == NotificationSeverity.MEDIUM
        assert notification.channel == NotificationChannel.IN_APP
        assert "test" in notification.tags
        assert "basic" in notification.tags

    async def test_create_notification_with_metadata(self, notification_service: NotificationService) -> None:
        """Create notification with metadata."""
        user_id = _unique_user_id()

        notification = await notification_service.create_notification(
            user_id=user_id,
            subject="With Metadata",
            body="Body",
            tags=["meta"],
            action_url="/api/v1/executions/exec-123/result",
            metadata={"execution_id": "exec-123", "duration": 45.5},
        )

        assert notification.metadata is not None
        assert notification.metadata.get("execution_id") == "exec-123"
        assert notification.metadata.get("duration") == 45.5

    async def test_create_notification_with_action_url(self, notification_service: NotificationService) -> None:
        """Create notification with action URL."""
        user_id = _unique_user_id()

        notification = await notification_service.create_notification(
            user_id=user_id,
            subject="Action Required",
            body="Click to view",
            tags=["action"],
            action_url="/api/v1/executions/exec-123/result",
        )

        assert notification.action_url == "/api/v1/executions/exec-123/result"

    async def test_create_notification_all_severities(self, notification_service: NotificationService) -> None:
        """Create notifications with all severity levels."""

        severities = [
            NotificationSeverity.LOW,
            NotificationSeverity.MEDIUM,
            NotificationSeverity.HIGH,
            NotificationSeverity.URGENT,
        ]

        for severity in severities:
            user_id = _unique_user_id()
            notification = await notification_service.create_notification(
                user_id=user_id,
                subject=f"Severity {severity}",
                body="Body",
                tags=["severity-test"],
                action_url=_TEST_ACTION_URL,
                severity=severity,
            )
            assert notification.severity == severity

    async def test_create_notification_empty_tags_raises(self, notification_service: NotificationService) -> None:
        """Create notification with empty tags raises validation error."""
        user_id = _unique_user_id()

        with pytest.raises(NotificationValidationError):
            await notification_service.create_notification(
                user_id=user_id,
                subject="No Tags",
                body="Body",
                tags=[],
                action_url=_TEST_ACTION_URL,
            )


class TestMarkAsRead:
    """Tests for mark_as_read method."""

    async def test_mark_as_read_success(self, notification_service: NotificationService) -> None:
        """Mark notification as read successfully."""
        user_id = _unique_user_id()

        # Create notification
        notification = await notification_service.create_notification(
            user_id=user_id,
            subject="To Read",
            body="Body",
            tags=["read-test"],
            action_url=_TEST_ACTION_URL,
        )

        # Mark as read
        await notification_service.mark_as_read(user_id, notification.notification_id)

        # Verify status changed to READ
        result = await notification_service.list_notifications(user_id=user_id, status=NotificationStatus.READ)
        read_ids = [n.notification_id for n in result.notifications]
        assert notification.notification_id in read_ids

    async def test_mark_as_read_nonexistent_raises(self, notification_service: NotificationService) -> None:
        """Mark nonexistent notification as read raises error."""
        user_id = _unique_user_id()

        with pytest.raises(NotificationNotFoundError):
            await notification_service.mark_as_read(user_id, "nonexistent-notification-id")


class TestMarkAllAsRead:
    """Tests for mark_all_as_read method."""

    async def test_mark_all_as_read(self, notification_service: NotificationService) -> None:
        """Mark all notifications as read."""
        user_id = _unique_user_id()

        # Create multiple notifications
        for i in range(3):
            await notification_service.create_notification(
                user_id=user_id,
                subject=f"Notification {i}",
                body="Body",
                tags=["bulk-read"],
                action_url=_TEST_ACTION_URL,
            )

        # Mark all as read
        count = await notification_service.mark_all_as_read(user_id)
        assert count == 3

        # Verify unread count is 0
        unread = await notification_service.get_unread_count(user_id)
        assert unread == 0


class TestGetUnreadCount:
    """Tests for get_unread_count method."""

    async def test_get_unread_count(self, notification_service: NotificationService) -> None:
        """Get unread notification count."""
        user_id = _unique_user_id()

        # Initial count should be 0
        initial = await notification_service.get_unread_count(user_id)
        assert initial == 0

        # Create notifications
        for _ in range(2):
            await notification_service.create_notification(
                user_id=user_id,
                subject="Unread",
                body="Body",
                tags=["count-test"],
                action_url=_TEST_ACTION_URL,
            )

        # Count should increase
        count = await notification_service.get_unread_count(user_id)
        assert count == 2


class TestListNotifications:
    """Tests for list_notifications method."""

    async def test_list_notifications_basic(self, notification_service: NotificationService) -> None:
        """List notifications with pagination."""
        user_id = _unique_user_id()

        # Create notifications
        for i in range(5):
            await notification_service.create_notification(
                user_id=user_id,
                subject=f"List Test {i}",
                body="Body",
                tags=["list-test"],
                action_url=_TEST_ACTION_URL,
            )

        # List with pagination
        result = await notification_service.list_notifications(user_id, limit=3, offset=0)

        assert len(result.notifications) == 3
        assert result.total == 5

    async def test_list_notifications_with_tag_filter(self, notification_service: NotificationService) -> None:
        """List notifications filtered by tags."""
        user_id = _unique_user_id()

        # Create with different tags
        await notification_service.create_notification(
            user_id=user_id,
            subject="Tagged A",
            body="Body",
            tags=["filter-a"],
            action_url=_TEST_ACTION_URL,
        )
        await notification_service.create_notification(
            user_id=user_id,
            subject="Tagged B",
            body="Body",
            tags=["filter-b"],
            action_url=_TEST_ACTION_URL,
        )

        # Filter by tag
        result = await notification_service.list_notifications(user_id, include_tags=["filter-a"])

        assert [n.subject for n in result.notifications] == ["Tagged A"]

    async def test_list_notifications_exclude_tags(self, notification_service: NotificationService) -> None:
        """List notifications excluding specific tags."""
        user_id = _unique_user_id()

        # Create notifications
        await notification_service.create_notification(
            user_id=user_id,
            subject="Include Me",
            body="Body",
            tags=["include"],
            action_url=_TEST_ACTION_URL,
        )
        await notification_service.create_notification(
            user_id=user_id,
            subject="Exclude Me",
            body="Body",
            tags=["exclude"],
            action_url=_TEST_ACTION_URL,
        )

        # List excluding 'exclude' tag
        result = await notification_service.list_notifications(user_id, exclude_tags=["exclude"])

        assert [n.subject for n in result.notifications] == ["Include Me"]


class TestDeleteNotification:
    """Tests for delete_notification method."""

    async def test_delete_notification_success(self, notification_service: NotificationService) -> None:
        """Delete notification successfully."""
        user_id = _unique_user_id()

        # Create notification
        notification = await notification_service.create_notification(
            user_id=user_id,
            subject="To Delete",
            body="Body",
            tags=["delete-test"],
            action_url=_TEST_ACTION_URL,
        )

        # Delete it
        await notification_service.delete_notification(user_id, notification.notification_id)

        # Verify it's gone
        result = await notification_service.list_notifications(user_id=user_id)
        remaining_ids = [n.notification_id for n in result.notifications]
        assert notification.notification_id not in remaining_ids

    async def test_delete_nonexistent_notification_raises(self, notification_service: NotificationService) -> None:
        """Delete nonexistent notification raises error."""
        user_id = _unique_user_id()

        with pytest.raises(NotificationNotFoundError):
            await notification_service.delete_notification(user_id, "nonexistent-id")


class TestSubscriptions:
    """Tests for subscription management."""

    async def test_update_subscription_in_app(
        self, notification_service: NotificationService, notification_repository: NotificationRepository
    ) -> None:
        """Update in-app subscription."""
        user_id = _unique_user_id()

        # Update subscription
        subscription = await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            changes=SubscriptionChanges(enabled=True),
        )

        assert subscription.channel == NotificationChannel.IN_APP
        assert subscription.enabled is True

        # Verify via notification_repository
        stored = await notification_repository.get_subscription(user_id, NotificationChannel.IN_APP)
        assert stored is not None
        assert stored.enabled is True

    async def test_update_subscription_disable(self, notification_service: NotificationService) -> None:
        """Disable subscription channel."""
        user_id = _unique_user_id()

        # Enable first
        await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            changes=SubscriptionChanges(enabled=True),
        )

        # Then disable
        subscription = await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            changes=SubscriptionChanges(enabled=False),
        )

        assert subscription.enabled is False

    async def test_update_subscription_with_severities(self, notification_service: NotificationService) -> None:
        """Update subscription with severity filter."""
        user_id = _unique_user_id()

        subscription = await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            changes=SubscriptionChanges(
                enabled=True,
                severities=[NotificationSeverity.HIGH, NotificationSeverity.URGENT],
            ),
        )

        assert subscription.severities is not None
        assert NotificationSeverity.HIGH in subscription.severities
        assert NotificationSeverity.URGENT in subscription.severities

    async def test_update_webhook_requires_url(self, notification_service: NotificationService) -> None:
        """Webhook subscription requires URL when enabled."""
        user_id = _unique_user_id()

        with pytest.raises(NotificationValidationError):
            await notification_service.update_subscription(
                user_id=user_id,
                channel=NotificationChannel.WEBHOOK,
                changes=SubscriptionChanges(enabled=True),
            )

    async def test_update_webhook_with_url(self, notification_service: NotificationService) -> None:
        """Webhook subscription with valid URL."""
        user_id = _unique_user_id()

        subscription = await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.WEBHOOK,
            changes=SubscriptionChanges(enabled=True, webhook_url="https://example.com/webhook"),
        )

        assert subscription.enabled is True
        assert subscription.webhook_url == "https://example.com/webhook"

    async def test_get_all_subscriptions(self, notification_service: NotificationService) -> None:
        """Get all subscriptions for user."""
        user_id = _unique_user_id()

        # Update a subscription
        await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            changes=SubscriptionChanges(enabled=True),
        )

        # Get all
        result = await notification_service.get_subscriptions(user_id)

        channels = [s.channel for s in result]
        assert NotificationChannel.IN_APP in channels


class TestSystemNotification:
    """Tests for create_system_notification method."""

    async def test_create_system_notification_to_users(self, notification_service: NotificationService) -> None:
        """Create system notification targeting specific users."""
        target_users = [_unique_user_id(), _unique_user_id()]

        stats = await notification_service.create_system_notification(
            title="System Alert",
            message="Important system message",
            severity=NotificationSeverity.HIGH,
            tags=["system", "alert"],
            target_users=target_users,
        )

        assert isinstance(stats, dict)
        assert stats["total_users"] == 2
        assert "created" in stats
        assert "failed" in stats
        assert "throttled" in stats

    async def test_create_system_notification_empty_targets(self, notification_service: NotificationService) -> None:
        """System notification with no targets returns zero stats."""

        stats = await notification_service.create_system_notification(
            title="No Targets",
            message="Message",
            target_users=[],
        )

        assert stats["total_users"] == 0
        assert stats["created"] == 0


class TestNotificationIntegration:
    """Integration tests for notification workflow."""

    async def test_full_notification_lifecycle(self, notification_service: NotificationService) -> None:
        """Test complete notification lifecycle: create -> read -> delete."""
        user_id = _unique_user_id()

        # Create
        notification = await notification_service.create_notification(
            user_id=user_id,
            subject="Lifecycle Test",
            body="Testing full lifecycle",
            tags=["lifecycle"],
            action_url=_TEST_ACTION_URL,
        )
        assert notification.notification_id is not None

        # Verify unread count increased
        unread = await notification_service.get_unread_count(user_id)
        assert unread == 1

        # Mark as read and verify unread count drops
        await notification_service.mark_as_read(user_id, notification.notification_id)
        unread_after_read = await notification_service.get_unread_count(user_id)
        assert unread_after_read < unread

        # Delete and verify it's gone
        await notification_service.delete_notification(user_id, notification.notification_id)
        result = await notification_service.list_notifications(user_id=user_id)
        remaining_ids = [n.notification_id for n in result.notifications]
        assert notification.notification_id not in remaining_ids

    async def test_notification_with_subscription_filter(self, notification_service: NotificationService) -> None:
        """Notification delivery respects subscription filters."""
        user_id = _unique_user_id()

        # Set up subscription with severity filter
        await notification_service.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            changes=SubscriptionChanges(enabled=True, severities=[NotificationSeverity.HIGH]),
        )

        # Create HIGH severity notification - should be delivered
        high_notif = await notification_service.create_notification(
            user_id=user_id,
            subject="High Priority",
            body="Body",
            tags=["filter-test"],
            action_url=_TEST_ACTION_URL,
            severity=NotificationSeverity.HIGH,
        )
        assert high_notif.notification_id is not None
