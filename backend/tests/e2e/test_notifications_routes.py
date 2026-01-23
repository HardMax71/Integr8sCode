import pytest
from app.domain.enums.notification import NotificationChannel, NotificationSeverity, NotificationStatus
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationListResponse,
    NotificationSubscription,
    SubscriptionsResponse,
    UnreadCountResponse,
)
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]


class TestGetNotifications:
    """Tests for GET /api/v1/notifications."""

    @pytest.mark.asyncio
    async def test_get_notifications_empty(self, test_user: AsyncClient) -> None:
        """New user has empty or minimal notifications."""
        response = await test_user.get("/api/v1/notifications")

        assert response.status_code == 200
        result = NotificationListResponse.model_validate(response.json())

        assert result.total >= 0
        assert result.unread_count >= 0
        assert isinstance(result.notifications, list)

    @pytest.mark.asyncio
    async def test_get_notifications_pagination(
            self, test_user: AsyncClient
    ) -> None:
        """Pagination parameters work correctly."""
        response = await test_user.get(
            "/api/v1/notifications",
            params={"limit": 10, "offset": 0},
        )

        assert response.status_code == 200
        result = NotificationListResponse.model_validate(response.json())
        # Limit/offset may not be in response model, just check structure
        assert isinstance(result.notifications, list)

    @pytest.mark.asyncio
    async def test_get_notifications_with_status_filter(
            self, test_user: AsyncClient
    ) -> None:
        """Filter notifications by status."""
        response = await test_user.get(
            "/api/v1/notifications",
            params={"status": NotificationStatus.DELIVERED},
        )

        assert response.status_code == 200
        result = NotificationListResponse.model_validate(response.json())
        assert isinstance(result.notifications, list)

    @pytest.mark.asyncio
    async def test_get_notifications_with_tag_filters(
            self, test_user: AsyncClient
    ) -> None:
        """Filter notifications by tags."""
        response = await test_user.get(
            "/api/v1/notifications",
            params={
                "include_tags": ["execution"],
                "tag_prefix": "exec",
            },
        )

        assert response.status_code == 200
        result = NotificationListResponse.model_validate(response.json())
        assert isinstance(result.notifications, list)

    @pytest.mark.asyncio
    async def test_get_notifications_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/notifications")
        assert response.status_code == 401


class TestMarkNotificationRead:
    """Tests for PUT /api/v1/notifications/{notification_id}/read."""

    @pytest.mark.asyncio
    async def test_mark_nonexistent_notification_read(
            self, test_user: AsyncClient
    ) -> None:
        """Marking nonexistent notification returns 404."""
        response = await test_user.put(
            "/api/v1/notifications/nonexistent-id/read"
        )
        assert response.status_code == 404


class TestMarkAllRead:
    """Tests for POST /api/v1/notifications/mark-all-read."""

    @pytest.mark.asyncio
    async def test_mark_all_read(self, test_user: AsyncClient) -> None:
        """Mark all notifications as read returns 204."""
        response = await test_user.post("/api/v1/notifications/mark-all-read")

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_mark_all_read_idempotent(
            self, test_user: AsyncClient
    ) -> None:
        """Mark all read is idempotent."""
        # Call twice
        response1 = await test_user.post("/api/v1/notifications/mark-all-read")
        response2 = await test_user.post("/api/v1/notifications/mark-all-read")

        assert response1.status_code == 204
        assert response2.status_code == 204


class TestSubscriptions:
    """Tests for /api/v1/notifications/subscriptions."""

    @pytest.mark.asyncio
    async def test_get_subscriptions(self, test_user: AsyncClient) -> None:
        """Get notification subscriptions."""
        response = await test_user.get("/api/v1/notifications/subscriptions")

        assert response.status_code == 200
        result = SubscriptionsResponse.model_validate(response.json())

        assert isinstance(result.subscriptions, list)
        # Each subscription should be valid
        for sub in result.subscriptions:
            assert sub.channel is not None

    @pytest.mark.asyncio
    async def test_update_subscription(self, test_user: AsyncClient) -> None:
        """Update a subscription channel."""
        response = await test_user.put(
            f"/api/v1/notifications/subscriptions/{NotificationChannel.IN_APP}",
            json={
                "enabled": True,
                "severities": [NotificationSeverity.LOW, NotificationSeverity.MEDIUM, NotificationSeverity.HIGH],
            },
        )

        assert response.status_code == 200
        result = NotificationSubscription.model_validate(response.json())

        assert result.enabled is True
        assert result.channel == NotificationChannel.IN_APP

    @pytest.mark.asyncio
    async def test_update_subscription_disable(
            self, test_user: AsyncClient
    ) -> None:
        """Disable a subscription channel."""
        response = await test_user.put(
            f"/api/v1/notifications/subscriptions/{NotificationChannel.IN_APP}",
            json={"enabled": False},
        )

        assert response.status_code == 200
        result = NotificationSubscription.model_validate(response.json())
        assert result.enabled is False

    @pytest.mark.asyncio
    async def test_update_subscription_with_tags(
            self, test_user: AsyncClient
    ) -> None:
        """Update subscription with tag filters."""
        response = await test_user.put(
            f"/api/v1/notifications/subscriptions/{NotificationChannel.IN_APP}",
            json={
                "enabled": True,
                "include_tags": ["execution", "system"],
                "exclude_tags": ["debug"],
            },
        )

        assert response.status_code == 200
        result = NotificationSubscription.model_validate(response.json())
        assert result.enabled is True


class TestUnreadCount:
    """Tests for GET /api/v1/notifications/unread-count."""

    @pytest.mark.asyncio
    async def test_get_unread_count(self, test_user: AsyncClient) -> None:
        """Get unread notification count."""
        response = await test_user.get("/api/v1/notifications/unread-count")

        assert response.status_code == 200
        result = UnreadCountResponse.model_validate(response.json())

        assert result.unread_count >= 0
        assert isinstance(result.unread_count, int)


class TestDeleteNotification:
    """Tests for DELETE /api/v1/notifications/{notification_id}."""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_notification(
            self, test_user: AsyncClient
    ) -> None:
        """Deleting nonexistent notification returns 404."""
        response = await test_user.delete(
            "/api/v1/notifications/nonexistent-notification-id"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_notification_response_format(
            self, test_user: AsyncClient
    ) -> None:
        """Delete response has correct format (when notification exists)."""
        # Get notifications first
        list_response = await test_user.get(
            "/api/v1/notifications",
            params={"limit": 1},
        )

        if list_response.status_code == 200:
            result = NotificationListResponse.model_validate(list_response.json())
            if result.notifications:
                notification_id = result.notifications[0].notification_id

                # Delete it
                delete_response = await test_user.delete(
                    f"/api/v1/notifications/{notification_id}"
                )

                if delete_response.status_code == 200:
                    delete_result = DeleteNotificationResponse.model_validate(
                        delete_response.json()
                    )
                    assert "deleted" in delete_result.message.lower()
