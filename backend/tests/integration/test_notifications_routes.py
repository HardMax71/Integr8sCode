import pytest
from app.domain.enums.notification import NotificationChannel, NotificationStatus
from app.domain.enums.user import UserRole
from app.schemas_pydantic.notification import (
    DeleteNotificationResponse,
    NotificationListResponse,
    NotificationSubscription,
    SubscriptionsResponse,
    UnreadCountResponse,
)
from httpx import AsyncClient

from tests.conftest import MakeUser


@pytest.mark.integration
class TestNotificationRoutes:
    """Test notification endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_notifications_require_authentication(self, client: AsyncClient) -> None:
        """Test that notification endpoints require authentication."""
        # Try to access notifications without auth
        response = await client.get("/api/v1/notifications")
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_list_user_notifications(self, authenticated_client: AsyncClient) -> None:
        """Test listing user's notifications."""
        # List notifications
        response = await authenticated_client.get("/api/v1/notifications?limit=10&offset=0")
        assert response.status_code == 200

        # Validate response structure
        notifications_data = response.json()
        notifications_response = NotificationListResponse(**notifications_data)

        # Verify basic fields
        assert isinstance(notifications_response.notifications, list)
        assert isinstance(notifications_response.total, int)
        assert isinstance(notifications_response.unread_count, int)

        # If there are notifications, validate their structure per schema
        for n in notifications_response.notifications:
            assert n.notification_id
            assert n.channel in [c.value for c in NotificationChannel]
            assert n.severity in ["low","medium","high","urgent"]
            assert isinstance(n.tags, list)
            assert n.status in [s.value for s in NotificationStatus]
            assert n.subject is not None
            assert n.body is not None
            assert n.created_at is not None

    @pytest.mark.asyncio
    async def test_filter_notifications_by_status(self, authenticated_client: AsyncClient) -> None:
        """Test filtering notifications by status."""
        # Test different status filters
        statuses = [
            NotificationStatus.READ.value,
            NotificationStatus.DELIVERED.value,
            NotificationStatus.SKIPPED.value,
        ]
        for status in statuses:
            response = await authenticated_client.get(f"/api/v1/notifications?status={status}&limit=5")
            assert response.status_code == 200

            notifications_data = response.json()
            notifications_response = NotificationListResponse(**notifications_data)

            # All returned notifications should have the requested status
            for notification in notifications_response.notifications:
                assert notification.status == status

    @pytest.mark.asyncio
    async def test_get_unread_count(self, authenticated_client: AsyncClient) -> None:
        """Test getting count of unread notifications."""
        # Get unread count
        response = await authenticated_client.get("/api/v1/notifications/unread-count")
        assert response.status_code == 200

        # Validate response
        count_data = response.json()
        unread_count = UnreadCountResponse(**count_data)

        assert isinstance(unread_count.unread_count, int)
        assert unread_count.unread_count >= 0

        # Note: listing cannot filter 'unread' directly; count is authoritative

    @pytest.mark.asyncio
    async def test_mark_notification_as_read(self, authenticated_client: AsyncClient) -> None:
        """Test marking a notification as read."""
        # Get an unread notification
        notifications_response = await authenticated_client.get(
            f"/api/v1/notifications?status={NotificationStatus.DELIVERED.value}&limit=1")
        assert notifications_response.status_code == 200

        notifications_data = notifications_response.json()
        if notifications_data["total"] > 0 and notifications_data["notifications"]:
            notification_id = notifications_data["notifications"][0]["notification_id"]

            # Mark as read
            mark_response = await authenticated_client.put(f"/api/v1/notifications/{notification_id}/read")
            assert mark_response.status_code == 204

            # Verify it's now marked as read
            updated_response = await authenticated_client.get("/api/v1/notifications")
            assert updated_response.status_code == 200

            updated_data = updated_response.json()
            # Find the notification and check its status
            for notif in updated_data["notifications"]:
                if notif["notification_id"] == notification_id:
                    assert notif["status"] == "read"
                    break

    @pytest.mark.asyncio
    async def test_mark_nonexistent_notification_as_read(self, authenticated_client: AsyncClient) -> None:
        """Test marking a non-existent notification as read."""
        fake_notification_id = "00000000-0000-0000-0000-000000000000"
        response = await authenticated_client.put(f"/api/v1/notifications/{fake_notification_id}/read")
        assert response.status_code == 404

        error_data = response.json()
        assert "detail" in error_data
        assert "not found" in error_data["detail"].lower()

    @pytest.mark.asyncio
    async def test_mark_all_notifications_as_read(self, authenticated_client: AsyncClient) -> None:
        """Test marking all notifications as read."""
        # Mark all as read
        mark_all_response = await authenticated_client.post("/api/v1/notifications/mark-all-read")
        assert mark_all_response.status_code == 204

        # Verify unread count is now 0
        count_response = await authenticated_client.get("/api/v1/notifications/unread-count")
        assert count_response.status_code == 200
        count_data = count_response.json()
        assert count_data["unread_count"] == 0

    @pytest.mark.asyncio
    async def test_get_notification_subscriptions(self, authenticated_client: AsyncClient) -> None:
        """Test getting user's notification subscriptions."""
        # Get subscriptions
        response = await authenticated_client.get("/api/v1/notifications/subscriptions")
        assert response.status_code == 200

        # Validate response
        subscriptions_data = response.json()
        subscriptions_response = SubscriptionsResponse(**subscriptions_data)

        assert isinstance(subscriptions_response.subscriptions, list)

        # Check each subscription
        for subscription in subscriptions_response.subscriptions:
            assert isinstance(subscription, NotificationSubscription)
            assert subscription.channel in [c.value for c in NotificationChannel]
            assert isinstance(subscription.enabled, bool)
            assert subscription.user_id is not None

            # Validate optional fields present in the schema
            assert isinstance(subscription.severities, list)
            assert isinstance(subscription.include_tags, list)
            assert isinstance(subscription.exclude_tags, list)

            # Check webhook URLs if present
            if subscription.webhook_url:
                assert isinstance(subscription.webhook_url, str)
                assert subscription.webhook_url.startswith("http")
            if subscription.slack_webhook:
                assert isinstance(subscription.slack_webhook, str)
                assert subscription.slack_webhook.startswith("http")

    @pytest.mark.asyncio
    async def test_update_notification_subscription(self, authenticated_client: AsyncClient) -> None:
        """Test updating a notification subscription."""
        # Update in_app subscription
        update_data = {
            "enabled": True,
            "severities": ["medium","high"],
            "include_tags": ["execution"],
            "exclude_tags": ["external_alert"]
        }

        response = await authenticated_client.put("/api/v1/notifications/subscriptions/in_app", json=update_data)
        assert response.status_code == 200

        # Validate response
        updated_sub_data = response.json()
        updated_subscription = NotificationSubscription(**updated_sub_data)

        assert updated_subscription.channel == "in_app"
        assert updated_subscription.enabled == update_data["enabled"]
        assert updated_subscription.severities == update_data["severities"]
        assert updated_subscription.include_tags == update_data["include_tags"]
        assert updated_subscription.exclude_tags == update_data["exclude_tags"]

        # Verify the update persisted
        get_response = await authenticated_client.get("/api/v1/notifications/subscriptions")
        assert get_response.status_code == 200

        subs_data = get_response.json()
        for sub in subs_data["subscriptions"]:
            if sub["channel"] == "in_app":
                assert sub["enabled"] == update_data["enabled"]
                assert sub["severities"] == update_data["severities"]
                assert sub["include_tags"] == update_data["include_tags"]
                assert sub["exclude_tags"] == update_data["exclude_tags"]
                break

    @pytest.mark.asyncio
    async def test_update_webhook_subscription(self, authenticated_client: AsyncClient) -> None:
        """Test updating webhook subscription with URL."""
        # Update webhook subscription
        update_data = {
            "enabled": True,
            "webhook_url": "https://example.com/webhook/notifications",
            "severities": ["medium","high"],
            "include_tags": ["execution"],
            "exclude_tags": []
        }

        response = await authenticated_client.put("/api/v1/notifications/subscriptions/webhook", json=update_data)
        assert response.status_code == 200

        # Validate response
        updated_sub_data = response.json()
        updated_subscription = NotificationSubscription(**updated_sub_data)

        assert updated_subscription.channel == "webhook"
        assert updated_subscription.enabled == update_data["enabled"]
        assert updated_subscription.webhook_url == update_data["webhook_url"]
        assert updated_subscription.severities == update_data["severities"]

    @pytest.mark.asyncio
    async def test_update_slack_subscription(self, authenticated_client: AsyncClient) -> None:
        """Test updating Slack subscription with webhook."""
        # Update Slack subscription
        update_data = {
            "enabled": True,
            "slack_webhook": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX",
            "severities": ["high","urgent"],
            "include_tags": ["execution","error"],
            "exclude_tags": []
        }

        response = await authenticated_client.put("/api/v1/notifications/subscriptions/slack", json=update_data)
        # Slack subscription may be disabled by config; 422 indicates validation
        assert response.status_code in [200, 422]
        if response.status_code == 422:
            err = response.json()
            assert "detail" in err
            return
        # Validate response
        updated_sub_data = response.json()
        updated_subscription = NotificationSubscription(**updated_sub_data)
        assert updated_subscription.channel == "slack"
        assert updated_subscription.enabled == update_data["enabled"]
        assert updated_subscription.slack_webhook == update_data["slack_webhook"]
        assert updated_subscription.severities == update_data["severities"]

    @pytest.mark.asyncio
    async def test_delete_notification(self, authenticated_client: AsyncClient) -> None:
        """Test deleting a notification."""
        # Get a notification to delete
        notifications_response = await authenticated_client.get("/api/v1/notifications?limit=1")
        assert notifications_response.status_code == 200

        notifications_data = notifications_response.json()
        if notifications_data["total"] > 0 and notifications_data["notifications"]:
            notification_id = notifications_data["notifications"][0]["notification_id"]

            # Delete the notification
            delete_response = await authenticated_client.delete(f"/api/v1/notifications/{notification_id}")
            assert delete_response.status_code == 200

            # Validate response
            delete_data = delete_response.json()
            delete_result = DeleteNotificationResponse(**delete_data)
            assert "deleted" in delete_result.message.lower()

            # Verify it's deleted
            list_response = await authenticated_client.get("/api/v1/notifications")
            assert list_response.status_code == 200

            list_data = list_response.json()
            # Should not find the deleted notification
            notification_ids = [n["notification_id"] for n in list_data["notifications"]]
            assert notification_id not in notification_ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_notification(self, authenticated_client: AsyncClient) -> None:
        """Test deleting a non-existent notification."""
        # Try to delete non-existent notification
        fake_notification_id = "00000000-0000-0000-0000-000000000000"
        response = await authenticated_client.delete(f"/api/v1/notifications/{fake_notification_id}")
        assert response.status_code == 404

        error_data = response.json()
        assert "detail" in error_data
        assert "not found" in error_data["detail"].lower()

    @pytest.mark.asyncio
    async def test_notification_pagination(self, authenticated_client: AsyncClient) -> None:
        """Test notification pagination."""
        # Get first page
        page1_response = await authenticated_client.get("/api/v1/notifications?limit=5&offset=0")
        assert page1_response.status_code == 200

        page1_data = page1_response.json()
        page1 = NotificationListResponse(**page1_data)

        # If there are more than 5 notifications, get second page
        if page1.total > 5:
            page2_response = await authenticated_client.get("/api/v1/notifications?limit=5&offset=5")
            assert page2_response.status_code == 200

            page2_data = page2_response.json()
            page2 = NotificationListResponse(**page2_data)

            # Verify pagination metadata via totals only
            assert page2.total == page1.total

            # Notifications should be different
            if page1.notifications and page2.notifications:
                page1_ids = {n.notification_id for n in page1.notifications}
                page2_ids = {n.notification_id for n in page2.notifications}
                # Should have no overlap
                assert len(page1_ids.intersection(page2_ids)) == 0

    @pytest.mark.asyncio
    async def test_notifications_isolation_between_users(
        self, client: AsyncClient, make_user: MakeUser,
    ) -> None:
        """Test that notifications are isolated between users."""
        # Create user and fetch notifications immediately (make_user logs in)
        await make_user(UserRole.USER)
        user_notifications_response = await client.get("/api/v1/notifications")
        assert user_notifications_response.status_code == 200
        user_notification_ids = [
            n["notification_id"] for n in user_notifications_response.json()["notifications"]
        ]

        # Create admin and fetch notifications immediately (make_user logs in)
        await make_user(UserRole.ADMIN)
        admin_notifications_response = await client.get("/api/v1/notifications")
        assert admin_notifications_response.status_code == 200
        admin_notification_ids = [
            n["notification_id"] for n in admin_notifications_response.json()["notifications"]
        ]

        # Notifications should be different (no overlap)
        if user_notification_ids and admin_notification_ids:
            assert len(set(user_notification_ids).intersection(set(admin_notification_ids))) == 0

    @pytest.mark.asyncio
    async def test_invalid_notification_channel(self, authenticated_client: AsyncClient) -> None:
        """Test updating subscription with invalid channel."""
        # Try invalid channel
        update_data = {
            "enabled": True,
            "severities": ["medium"]
        }

        response = await authenticated_client.put(
            "/api/v1/notifications/subscriptions/invalid_channel", json=update_data
        )
        assert response.status_code in [400, 404, 422]
