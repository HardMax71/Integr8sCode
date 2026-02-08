import pytest
from app.domain.enums.notification import NotificationChannel, NotificationSeverity, NotificationStatus
from app.schemas_pydantic.execution import ExecutionResponse
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationListResponse,
    NotificationResponse,
    NotificationSubscription,
    SubscriptionsResponse,
    UnreadCountResponse,
)
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


class TestGetNotifications:
    """Tests for GET /api/v1/notifications."""

    @pytest.mark.asyncio
    async def test_get_notifications_empty(self, test_user: AsyncClient) -> None:
        """New user has empty or minimal notifications."""
        response = await test_user.get("/api/v1/notifications")

        assert response.status_code == 200
        result = NotificationListResponse.model_validate(response.json())

        assert result.total == 0
        assert result.unread_count == 0
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
        for n in result.notifications:
            assert n.status == NotificationStatus.DELIVERED

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
        for n in result.notifications:
            assert any(t.startswith("exec") for t in n.tags)

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
            "/api/v1/notifications/00000000-0000-0000-0000-000000000000/read"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_mark_notification_read(
            self,
            test_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """Mark existing notification as read."""
        _, notification = execution_with_notification

        response = await test_user.put(
            f"/api/v1/notifications/{notification.notification_id}/read"
        )

        assert response.status_code == 204

        # Verify state actually changed
        get_resp = await test_user.get("/api/v1/notifications")
        assert get_resp.status_code == 200
        result = NotificationListResponse.model_validate(get_resp.json())
        marked = [n for n in result.notifications if n.notification_id == notification.notification_id]
        assert len(marked) == 1
        assert marked[0].read_at is not None


class TestMarkAllRead:
    """Tests for POST /api/v1/notifications/mark-all-read."""

    @pytest.mark.asyncio
    async def test_mark_all_read(
            self,
            test_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """Mark all notifications as read returns 204."""
        _, notification = execution_with_notification

        response = await test_user.post("/api/v1/notifications/mark-all-read")
        assert response.status_code == 204

        # Verify the specific notification was marked as read.
        # We assert on the individual notification rather than global unread_count
        # because other tests create executions (via created_execution without
        # waiting for notifications) whose async notifications can arrive between
        # mark-all-read and any subsequent count query.
        resp = await test_user.get("/api/v1/notifications")
        assert resp.status_code == 200
        result = NotificationListResponse.model_validate(resp.json())
        target = [n for n in result.notifications if n.notification_id == notification.notification_id]
        assert len(target) == 1
        assert target[0].read_at is not None

    @pytest.mark.asyncio
    async def test_mark_all_read_idempotent(
            self, test_user: AsyncClient
    ) -> None:
        """Mark all read is idempotent."""
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
        for sub in result.subscriptions:
            assert sub.channel in list(NotificationChannel)

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
        expected_severities = {NotificationSeverity.LOW, NotificationSeverity.MEDIUM, NotificationSeverity.HIGH}
        assert set(result.severities) == expected_severities

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
        assert result.include_tags == ["execution", "system"]
        assert result.exclude_tags == ["debug"]


class TestUnreadCount:
    """Tests for GET /api/v1/notifications/unread-count."""

    @pytest.mark.asyncio
    async def test_get_unread_count(
            self,
            test_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """Get unread notification count."""
        response = await test_user.get("/api/v1/notifications/unread-count")

        assert response.status_code == 200
        result = UnreadCountResponse.model_validate(response.json())

        assert result.unread_count >= 1


class TestDeleteNotification:
    """Tests for DELETE /api/v1/notifications/{notification_id}."""

    @pytest.mark.asyncio
    async def test_delete_nonexistent_notification(
            self, test_user: AsyncClient
    ) -> None:
        """Deleting nonexistent notification returns 404."""
        response = await test_user.delete(
            "/api/v1/notifications/00000000-0000-0000-0000-000000000000"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_notification(
            self,
            test_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """Delete existing notification returns success."""
        _, notification = execution_with_notification

        response = await test_user.delete(
            f"/api/v1/notifications/{notification.notification_id}"
        )

        assert response.status_code == 200
        result = DeleteNotificationResponse.model_validate(response.json())
        assert "deleted" in result.message.lower()

        # Verify notification is actually gone
        get_resp = await test_user.get("/api/v1/notifications")
        assert get_resp.status_code == 200
        remaining = NotificationListResponse.model_validate(get_resp.json())
        remaining_ids = [n.notification_id for n in remaining.notifications]
        assert notification.notification_id not in remaining_ids


class TestNotificationIsolation:
    """Tests for notification access isolation between users."""

    @pytest.mark.asyncio
    async def test_user_cannot_see_other_users_notifications(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """User's notification list does not include other users' notifications."""
        _, notification = execution_with_notification

        response = await another_user.get("/api/v1/notifications")
        assert response.status_code == 200

        result = NotificationListResponse.model_validate(response.json())
        notification_ids = [n.notification_id for n in result.notifications]

        assert notification.notification_id not in notification_ids

    @pytest.mark.asyncio
    async def test_cannot_mark_other_users_notification_read(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """Cannot mark another user's notification as read."""
        _, notification = execution_with_notification

        response = await another_user.put(
            f"/api/v1/notifications/{notification.notification_id}/read"
        )

        assert response.status_code == 404

        # Verify owner CAN mark it
        owner_resp = await test_user.put(
            f"/api/v1/notifications/{notification.notification_id}/read"
        )
        assert owner_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_cannot_delete_other_users_notification(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            execution_with_notification: tuple[ExecutionResponse, NotificationResponse],
    ) -> None:
        """Cannot delete another user's notification."""
        _, notification = execution_with_notification

        response = await another_user.delete(
            f"/api/v1/notifications/{notification.notification_id}"
        )

        assert response.status_code == 404

        # Verify owner CAN delete it
        owner_resp = await test_user.delete(
            f"/api/v1/notifications/{notification.notification_id}"
        )
        assert owner_resp.status_code == 200
