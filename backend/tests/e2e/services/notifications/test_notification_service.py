import uuid

import pytest
from app.db.repositories import NotificationRepository
from app.domain.enums import NotificationChannel, NotificationSeverity, NotificationStatus
from app.domain.notification import (
    DomainNotificationListResult,
    NotificationNotFoundError,
    NotificationValidationError,
)
from app.services.notification_service import NotificationService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


_TEST_ACTION_URL = "/api/v1/notifications"


def _unique_user_id() -> str:
    return f"notif_user_{uuid.uuid4().hex[:8]}"


class TestCreateNotification:
    """Tests for create_notification method."""

    @pytest.mark.asyncio
    async def test_create_notification_basic(self, scope: AsyncContainer) -> None:
        """Create basic in-app notification."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        notification = await svc.create_notification(
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

    @pytest.mark.asyncio
    async def test_create_notification_with_metadata(
        self, scope: AsyncContainer
    ) -> None:
        """Create notification with metadata."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        notification = await svc.create_notification(
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

    @pytest.mark.asyncio
    async def test_create_notification_with_action_url(
        self, scope: AsyncContainer
    ) -> None:
        """Create notification with action URL."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        notification = await svc.create_notification(
            user_id=user_id,
            subject="Action Required",
            body="Click to view",
            tags=["action"],
            action_url="/api/v1/executions/exec-123/result",
        )

        assert notification.action_url == "/api/v1/executions/exec-123/result"

    @pytest.mark.asyncio
    async def test_create_notification_all_severities(
        self, scope: AsyncContainer
    ) -> None:
        """Create notifications with all severity levels."""
        svc: NotificationService = await scope.get(NotificationService)

        severities = [
            NotificationSeverity.LOW,
            NotificationSeverity.MEDIUM,
            NotificationSeverity.HIGH,
            NotificationSeverity.URGENT,
        ]

        for severity in severities:
            user_id = _unique_user_id()
            notification = await svc.create_notification(
                user_id=user_id,
                subject=f"Severity {severity}",
                body="Body",
                tags=["severity-test"],
                action_url=_TEST_ACTION_URL,
                severity=severity,
            )
            assert notification.severity == severity

    @pytest.mark.asyncio
    async def test_create_notification_empty_tags_raises(
        self, scope: AsyncContainer
    ) -> None:
        """Create notification with empty tags raises validation error."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        with pytest.raises(NotificationValidationError):
            await svc.create_notification(
                user_id=user_id,
                subject="No Tags",
                body="Body",
                tags=[],
                action_url=_TEST_ACTION_URL,
            )


class TestMarkAsRead:
    """Tests for mark_as_read method."""

    @pytest.mark.asyncio
    async def test_mark_as_read_success(self, scope: AsyncContainer) -> None:
        """Mark notification as read successfully."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create notification
        notification = await svc.create_notification(
            user_id=user_id,
            subject="To Read",
            body="Body",
            tags=["read-test"],
            action_url=_TEST_ACTION_URL,
        )

        # Mark as read
        await svc.mark_as_read(user_id, notification.notification_id)

        # Verify status changed to READ
        result = await svc.list_notifications(user_id=user_id, status=NotificationStatus.READ)
        read_ids = [n.notification_id for n in result.notifications]
        assert notification.notification_id in read_ids

    @pytest.mark.asyncio
    async def test_mark_as_read_nonexistent_raises(
        self, scope: AsyncContainer
    ) -> None:
        """Mark nonexistent notification as read raises error."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        with pytest.raises(NotificationNotFoundError):
            await svc.mark_as_read(user_id, "nonexistent-notification-id")


class TestMarkAllAsRead:
    """Tests for mark_all_as_read method."""

    @pytest.mark.asyncio
    async def test_mark_all_as_read(self, scope: AsyncContainer) -> None:
        """Mark all notifications as read."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create multiple notifications
        for i in range(3):
            await svc.create_notification(
                user_id=user_id,
                subject=f"Notification {i}",
                body="Body",
                tags=["bulk-read"],
                action_url=_TEST_ACTION_URL,
            )

        # Mark all as read
        count = await svc.mark_all_as_read(user_id)
        assert count >= 3

        # Verify unread count is 0
        unread = await svc.get_unread_count(user_id)
        assert unread == 0


class TestGetUnreadCount:
    """Tests for get_unread_count method."""

    @pytest.mark.asyncio
    async def test_get_unread_count(self, scope: AsyncContainer) -> None:
        """Get unread notification count."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Initial count should be 0
        initial = await svc.get_unread_count(user_id)
        assert initial == 0

        # Create notifications
        for _ in range(2):
            await svc.create_notification(
                user_id=user_id,
                subject="Unread",
                body="Body",
                tags=["count-test"],
                action_url=_TEST_ACTION_URL,
            )

        # Count should increase
        count = await svc.get_unread_count(user_id)
        assert count >= 2


class TestListNotifications:
    """Tests for list_notifications method."""

    @pytest.mark.asyncio
    async def test_list_notifications_basic(self, scope: AsyncContainer) -> None:
        """List notifications with pagination."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create notifications
        for i in range(5):
            await svc.create_notification(
                user_id=user_id,
                subject=f"List Test {i}",
                body="Body",
                tags=["list-test"],
                action_url=_TEST_ACTION_URL,
            )

        # List with pagination
        result = await svc.list_notifications(user_id, limit=3, offset=0)

        assert isinstance(result, DomainNotificationListResult)
        assert len(result.notifications) <= 3
        assert result.total >= 5

    @pytest.mark.asyncio
    async def test_list_notifications_with_tag_filter(
        self, scope: AsyncContainer
    ) -> None:
        """List notifications filtered by tags."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create with different tags
        await svc.create_notification(
            user_id=user_id,
            subject="Tagged A",
            body="Body",
            tags=["filter-a"],
            action_url=_TEST_ACTION_URL,
        )
        await svc.create_notification(
            user_id=user_id,
            subject="Tagged B",
            body="Body",
            tags=["filter-b"],
            action_url=_TEST_ACTION_URL,
        )

        # Filter by tag
        result = await svc.list_notifications(
            user_id, include_tags=["filter-a"]
        )

        assert isinstance(result, DomainNotificationListResult)
        for notif in result.notifications:
            assert "filter-a" in notif.tags

    @pytest.mark.asyncio
    async def test_list_notifications_exclude_tags(
        self, scope: AsyncContainer
    ) -> None:
        """List notifications excluding specific tags."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create notifications
        await svc.create_notification(
            user_id=user_id,
            subject="Include Me",
            body="Body",
            tags=["include"],
            action_url=_TEST_ACTION_URL,
        )
        await svc.create_notification(
            user_id=user_id,
            subject="Exclude Me",
            body="Body",
            tags=["exclude"],
            action_url=_TEST_ACTION_URL,
        )

        # List excluding 'exclude' tag
        result = await svc.list_notifications(
            user_id, exclude_tags=["exclude"]
        )

        assert isinstance(result, DomainNotificationListResult)
        for notif in result.notifications:
            assert "exclude" not in notif.tags


class TestDeleteNotification:
    """Tests for delete_notification method."""

    @pytest.mark.asyncio
    async def test_delete_notification_success(self, scope: AsyncContainer) -> None:
        """Delete notification successfully."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create notification
        notification = await svc.create_notification(
            user_id=user_id,
            subject="To Delete",
            body="Body",
            tags=["delete-test"],
            action_url=_TEST_ACTION_URL,
        )

        # Delete it
        await svc.delete_notification(user_id, notification.notification_id)

        # Verify it's gone
        result = await svc.list_notifications(user_id=user_id)
        remaining_ids = [n.notification_id for n in result.notifications]
        assert notification.notification_id not in remaining_ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_notification_raises(
        self, scope: AsyncContainer
    ) -> None:
        """Delete nonexistent notification raises error."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        with pytest.raises(NotificationNotFoundError):
            await svc.delete_notification(user_id, "nonexistent-id")


class TestSubscriptions:
    """Tests for subscription management."""

    @pytest.mark.asyncio
    async def test_update_subscription_in_app(self, scope: AsyncContainer) -> None:
        """Update in-app subscription."""
        svc: NotificationService = await scope.get(NotificationService)
        repo: NotificationRepository = await scope.get(NotificationRepository)
        user_id = _unique_user_id()

        # Update subscription
        subscription = await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            enabled=True,
        )

        assert subscription.channel == NotificationChannel.IN_APP
        assert subscription.enabled is True

        # Verify via repo
        stored = await repo.get_subscription(user_id, NotificationChannel.IN_APP)
        assert stored is not None
        assert stored.enabled is True

    @pytest.mark.asyncio
    async def test_update_subscription_disable(self, scope: AsyncContainer) -> None:
        """Disable subscription channel."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Enable first
        await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            enabled=True,
        )

        # Then disable
        subscription = await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            enabled=False,
        )

        assert subscription.enabled is False

    @pytest.mark.asyncio
    async def test_update_subscription_with_severities(
        self, scope: AsyncContainer
    ) -> None:
        """Update subscription with severity filter."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        subscription = await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            enabled=True,
            severities=[NotificationSeverity.HIGH, NotificationSeverity.URGENT],
        )

        assert subscription.severities is not None
        assert NotificationSeverity.HIGH in subscription.severities
        assert NotificationSeverity.URGENT in subscription.severities

    @pytest.mark.asyncio
    async def test_update_webhook_requires_url(self, scope: AsyncContainer) -> None:
        """Webhook subscription requires URL when enabled."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        with pytest.raises(NotificationValidationError):
            await svc.update_subscription(
                user_id=user_id,
                channel=NotificationChannel.WEBHOOK,
                enabled=True,
                # No webhook_url provided
            )

    @pytest.mark.asyncio
    async def test_update_webhook_with_url(self, scope: AsyncContainer) -> None:
        """Webhook subscription with valid URL."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        subscription = await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.WEBHOOK,
            enabled=True,
            webhook_url="https://example.com/webhook",
        )

        assert subscription.enabled is True
        assert subscription.webhook_url == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_get_all_subscriptions(self, scope: AsyncContainer) -> None:
        """Get all subscriptions for user."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Update a subscription
        await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            enabled=True,
        )

        # Get all
        subscriptions = await svc.get_subscriptions(user_id)

        assert isinstance(subscriptions, dict)
        assert NotificationChannel.IN_APP in subscriptions


class TestSystemNotification:
    """Tests for create_system_notification method."""

    @pytest.mark.asyncio
    async def test_create_system_notification_to_users(
        self, scope: AsyncContainer
    ) -> None:
        """Create system notification targeting specific users."""
        svc: NotificationService = await scope.get(NotificationService)
        target_users = [_unique_user_id(), _unique_user_id()]

        stats = await svc.create_system_notification(
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

    @pytest.mark.asyncio
    async def test_create_system_notification_empty_targets(
        self, scope: AsyncContainer
    ) -> None:
        """System notification with no targets returns zero stats."""
        svc: NotificationService = await scope.get(NotificationService)

        stats = await svc.create_system_notification(
            title="No Targets",
            message="Message",
            target_users=[],
        )

        assert stats["total_users"] == 0
        assert stats["created"] == 0


class TestNotificationIntegration:
    """Integration tests for notification workflow."""

    @pytest.mark.asyncio
    async def test_full_notification_lifecycle(self, scope: AsyncContainer) -> None:
        """Test complete notification lifecycle: create -> read -> delete."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Create
        notification = await svc.create_notification(
            user_id=user_id,
            subject="Lifecycle Test",
            body="Testing full lifecycle",
            tags=["lifecycle"],
            action_url=_TEST_ACTION_URL,
        )
        assert notification.notification_id is not None

        # Verify unread count increased
        unread = await svc.get_unread_count(user_id)
        assert unread >= 1

        # Mark as read and verify unread count drops
        await svc.mark_as_read(user_id, notification.notification_id)
        unread_after_read = await svc.get_unread_count(user_id)
        assert unread_after_read < unread

        # Delete and verify it's gone
        await svc.delete_notification(user_id, notification.notification_id)
        result = await svc.list_notifications(user_id=user_id)
        remaining_ids = [n.notification_id for n in result.notifications]
        assert notification.notification_id not in remaining_ids

    @pytest.mark.asyncio
    async def test_notification_with_subscription_filter(
        self, scope: AsyncContainer
    ) -> None:
        """Notification delivery respects subscription filters."""
        svc: NotificationService = await scope.get(NotificationService)
        user_id = _unique_user_id()

        # Set up subscription with severity filter
        await svc.update_subscription(
            user_id=user_id,
            channel=NotificationChannel.IN_APP,
            enabled=True,
            severities=[NotificationSeverity.HIGH],
        )

        # Create HIGH severity notification - should be delivered
        high_notif = await svc.create_notification(
            user_id=user_id,
            subject="High Priority",
            body="Body",
            tags=["filter-test"],
            action_url=_TEST_ACTION_URL,
            severity=NotificationSeverity.HIGH,
        )
        assert high_notif.notification_id is not None
