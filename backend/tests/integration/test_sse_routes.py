"""SSE integration tests - precise verification of Redis pub/sub and stream behavior."""

import json
from contextlib import aclosing
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.domain.enums.sse import SSEControlEvent, SSENotificationEvent
from app.domain.events.typed import EventMetadata, PodCreatedEvent
from app.schemas_pydantic.sse import (
    RedisNotificationMessage,
    RedisSSEMessage,
    SSEHealthResponse,
)
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_service import SSEService
from dishka import AsyncContainer
from httpx import AsyncClient


@pytest.mark.integration
class TestSSEAuth:
    """SSE endpoints require authentication."""

    @pytest.mark.asyncio
    async def test_notification_stream_requires_auth(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/events/notifications/stream")).status_code == 401

    @pytest.mark.asyncio
    async def test_execution_stream_requires_auth(self, client: AsyncClient) -> None:
        assert (await client.get(f"/api/v1/events/executions/{uuid4()}")).status_code == 401

    @pytest.mark.asyncio
    async def test_health_requires_auth(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/events/health")).status_code == 401


@pytest.mark.integration
class TestSSEHealth:
    """SSE health endpoint."""

    @pytest.mark.asyncio
    async def test_returns_valid_health_status(self, test_user: AsyncClient) -> None:
        r = await test_user.get("/api/v1/events/health")
        assert r.status_code == 200
        health = SSEHealthResponse.model_validate(r.json())
        assert health.status in ("healthy", "degraded", "unhealthy", "draining")
        assert health.active_connections >= 0


@pytest.mark.integration
class TestRedisPubSubExecution:
    """Redis pub/sub for execution events - verifies message structure and delivery."""

    @pytest.mark.asyncio
    async def test_publish_wraps_event_in_redis_message(self, scope: AsyncContainer) -> None:
        """publish_event wraps BaseEvent in RedisSSEMessage with correct structure."""
        bus: SSERedisBus = await scope.get(SSERedisBus)
        exec_id = f"exec-{uuid4().hex[:8]}"

        subscription = await bus.open_subscription(exec_id)

        event = PodCreatedEvent(
            execution_id=exec_id,
            pod_name="test-pod",
            namespace="test-ns",
            metadata=EventMetadata(service_name="test", service_version="1.0"),
        )
        await bus.publish_event(exec_id, event)

        # Verify the wrapper structure
        received: RedisSSEMessage | None = await subscription.get(RedisSSEMessage)
        await subscription.close()

        assert received is not None
        assert received.event_type == EventType.POD_CREATED
        assert received.execution_id == exec_id
        assert received.data["pod_name"] == "test-pod"
        assert received.data["namespace"] == "test-ns"

    @pytest.mark.asyncio
    async def test_channel_isolation(self, scope: AsyncContainer) -> None:
        """Different execution_ids use isolated channels."""
        bus: SSERedisBus = await scope.get(SSERedisBus)
        exec_a, exec_b = f"exec-a-{uuid4().hex[:6]}", f"exec-b-{uuid4().hex[:6]}"

        sub_a = await bus.open_subscription(exec_a)
        sub_b = await bus.open_subscription(exec_b)

        event = PodCreatedEvent(
            execution_id=exec_a,
            pod_name="pod-a",
            namespace="default",
            metadata=EventMetadata(service_name="test", service_version="1"),
        )
        await bus.publish_event(exec_a, event)

        received_a = await sub_a.get(RedisSSEMessage)
        received_b = await sub_b.get(RedisSSEMessage)

        await sub_a.close()
        await sub_b.close()

        assert received_a is not None
        assert received_a.data["pod_name"] == "pod-a"
        assert received_b is None  # B should not receive A's message


@pytest.mark.integration
class TestRedisPubSubNotification:
    """Redis pub/sub for notifications - verifies message structure and delivery."""

    @pytest.mark.asyncio
    async def test_publish_sends_notification_directly(self, scope: AsyncContainer) -> None:
        """publish_notification sends RedisNotificationMessage JSON directly."""
        bus: SSERedisBus = await scope.get(SSERedisBus)
        user_id = f"user-{uuid4().hex[:8]}"

        subscription = await bus.open_notification_subscription(user_id)

        notification = RedisNotificationMessage(
            notification_id="notif-123",
            severity=NotificationSeverity.HIGH,
            status=NotificationStatus.PENDING,
            tags=["urgent", "system"],
            subject="Test Alert",
            body="This is a test notification",
            action_url="https://example.com/action",
            created_at=datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        await bus.publish_notification(user_id, notification)

        received: RedisNotificationMessage | None = await subscription.get(RedisNotificationMessage)
        await subscription.close()

        assert received is not None
        assert received.notification_id == "notif-123"
        assert received.severity == NotificationSeverity.HIGH
        assert received.status == NotificationStatus.PENDING
        assert received.tags == ["urgent", "system"]
        assert received.subject == "Test Alert"
        assert received.body == "This is a test notification"
        assert received.action_url == "https://example.com/action"

    @pytest.mark.asyncio
    async def test_user_channel_isolation(self, scope: AsyncContainer) -> None:
        """Different user_ids use isolated channels."""
        bus: SSERedisBus = await scope.get(SSERedisBus)
        user_a, user_b = f"user-a-{uuid4().hex[:6]}", f"user-b-{uuid4().hex[:6]}"

        sub_a = await bus.open_notification_subscription(user_a)
        sub_b = await bus.open_notification_subscription(user_b)

        notification = RedisNotificationMessage(
            notification_id="for-user-a",
            severity=NotificationSeverity.LOW,
            status=NotificationStatus.PENDING,
            tags=[],
            subject="Private",
            body="For user A only",
            action_url="",
            created_at=datetime.now(timezone.utc),
        )
        await bus.publish_notification(user_a, notification)

        received_a = await sub_a.get(RedisNotificationMessage)
        received_b = await sub_b.get(RedisNotificationMessage)

        await sub_a.close()
        await sub_b.close()

        assert received_a is not None
        assert received_a.notification_id == "for-user-a"
        assert received_b is None  # B should not receive A's notification


@pytest.mark.integration
class TestSSEStreamEvents:
    """SSE stream control events - verifies event structure without pub/sub."""

    @pytest.mark.asyncio
    async def test_notification_stream_yields_connected_then_subscribed(self, scope: AsyncContainer) -> None:
        """Notification stream yields CONNECTED and SUBSCRIBED with correct fields."""
        sse_service: SSEService = await scope.get(SSEService)
        user_id = f"user-{uuid4().hex[:8]}"

        events: list[dict[str, Any]] = []
        async with aclosing(sse_service.create_notification_stream(user_id)) as stream:
            async for raw in stream:
                if "data" in raw:
                    events.append(json.loads(raw["data"]))
                if len(events) >= 2:
                    break

        # Verify CONNECTED event structure
        connected = events[0]
        assert connected["event_type"] == SSENotificationEvent.CONNECTED
        assert connected["user_id"] == user_id
        assert "timestamp" in connected
        assert connected["message"] == "Connected to notification stream"

        # Verify SUBSCRIBED event structure
        subscribed = events[1]
        assert subscribed["event_type"] == SSENotificationEvent.SUBSCRIBED
        assert subscribed["user_id"] == user_id
        assert "timestamp" in subscribed
        assert subscribed["message"] == "Redis subscription established"

    @pytest.mark.asyncio
    async def test_execution_stream_yields_connected_then_subscribed(self, scope: AsyncContainer) -> None:
        """Execution stream yields CONNECTED and SUBSCRIBED with correct fields."""
        sse_service: SSEService = await scope.get(SSEService)
        exec_id = f"exec-{uuid4().hex[:8]}"
        user_id = f"user-{uuid4().hex[:8]}"

        events: list[dict[str, Any]] = []
        async with aclosing(sse_service.create_execution_stream(exec_id, user_id)) as stream:
            async for raw in stream:
                if "data" in raw:
                    events.append(json.loads(raw["data"]))
                if len(events) >= 2:
                    break

        # Verify CONNECTED event structure
        connected = events[0]
        assert connected["event_type"] == SSEControlEvent.CONNECTED
        assert connected["execution_id"] == exec_id
        assert "connection_id" in connected
        assert connected["connection_id"].startswith(f"sse_{exec_id}_")
        assert "timestamp" in connected

        # Verify SUBSCRIBED event structure
        subscribed = events[1]
        assert subscribed["event_type"] == SSEControlEvent.SUBSCRIBED
        assert subscribed["execution_id"] == exec_id
        assert "timestamp" in subscribed
        assert subscribed["message"] == "Redis subscription established"

    @pytest.mark.asyncio
    async def test_concurrent_streams_get_unique_connection_ids(self, scope: AsyncContainer) -> None:
        """Each stream connection gets a unique connection_id."""
        import asyncio

        sse_service: SSEService = await scope.get(SSEService)
        exec_id = f"exec-{uuid4().hex[:8]}"

        async def get_connection_id(user_id: str) -> str:
            async with aclosing(sse_service.create_execution_stream(exec_id, user_id)) as stream:
                async for raw in stream:
                    if "data" in raw:
                        data = json.loads(raw["data"])
                        if data.get("event_type") == SSEControlEvent.CONNECTED:
                            return str(data["connection_id"])
            return ""

        conn_ids = await asyncio.gather(
            get_connection_id("user-1"),
            get_connection_id("user-2"),
            get_connection_id("user-3"),
        )

        # All connection IDs should be unique
        assert len(set(conn_ids)) == 3
        assert all(cid.startswith(f"sse_{exec_id}_") for cid in conn_ids)
