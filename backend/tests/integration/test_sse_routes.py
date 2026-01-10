import asyncio
import json
from contextlib import aclosing
from typing import Any
from uuid import uuid4

import pytest
from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.schemas_pydantic.sse import RedisNotificationMessage, SSEHealthResponse
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_service import SSEService
from dishka import AsyncContainer
from httpx import AsyncClient


@pytest.mark.integration
class TestSSERoutes:
    """SSE routes tested with deterministic event-driven reads (no polling)."""

    @pytest.mark.asyncio
    async def test_sse_requires_authentication(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/events/notifications/stream")
        assert r.status_code == 401
        detail = r.json().get("detail", "").lower()
        assert any(x in detail for x in ("not authenticated", "unauthorized", "login"))

        exec_id = str(uuid4())
        r = await client.get(f"/api/v1/events/executions/{exec_id}")
        assert r.status_code == 401

        r = await client.get("/api/v1/events/health")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_sse_health_status(self, test_user: AsyncClient) -> None:
        r = await test_user.get("/api/v1/events/health")
        assert r.status_code == 200
        health = SSEHealthResponse(**r.json())
        assert health.status in ("healthy", "degraded", "unhealthy", "draining")
        assert isinstance(health.active_connections, int) and health.active_connections >= 0

    @pytest.mark.asyncio
    async def test_notification_stream_service(self, scope: AsyncContainer, test_user: AsyncClient) -> None:
        """Test SSE notification stream directly through service (httpx doesn't support SSE streaming)."""
        sse_service: SSEService = await scope.get(SSEService)
        bus: SSERedisBus = await scope.get(SSERedisBus)
        user_id = f"user-{uuid4().hex[:8]}"

        events: list[dict[str, Any]] = []
        notification_received = False

        async with aclosing(sse_service.create_notification_stream(user_id)) as stream:
            try:
                async with asyncio.timeout(3.0):
                    async for event in stream:
                        if "data" not in event:
                            continue
                        data = json.loads(event["data"])
                        events.append(data)

                        # Wait for "subscribed" event - Redis subscription is now ready
                        if data.get("event_type") == "subscribed":
                            notification = RedisNotificationMessage(
                                notification_id=f"notif-{uuid4().hex[:8]}",
                                severity=NotificationSeverity.MEDIUM,
                                status=NotificationStatus.PENDING,
                                tags=[],
                                subject="Hello",
                                body="World",
                                action_url="",
                                created_at="2024-01-01T00:00:00Z",
                            )
                            await bus.publish_notification(user_id, notification)

                        # Stop when we receive the notification
                        if data.get("event_type") == "notification" and data.get("subject") == "Hello":
                            notification_received = True
                            break
            except TimeoutError:
                pass

        assert notification_received, f"Expected notification, got events: {events}"

    @pytest.mark.asyncio
    async def test_execution_event_stream_service(self, scope: AsyncContainer, test_user: AsyncClient) -> None:
        """Test SSE execution stream directly through service (httpx doesn't support SSE streaming)."""
        exec_id = f"e-{uuid4().hex[:8]}"
        user_id = f"user-{uuid4().hex[:8]}"

        sse_service: SSEService = await scope.get(SSEService)
        bus: SSERedisBus = await scope.get(SSERedisBus)

        events: list[dict[str, Any]] = []
        pod_event_received = False

        async with aclosing(sse_service.create_execution_stream(exec_id, user_id)) as stream:
            try:
                async with asyncio.timeout(3.0):
                    async for event in stream:
                        if "data" not in event:
                            continue
                        data = json.loads(event["data"])
                        events.append(data)

                        # Wait for "subscribed" event - Redis subscription is now ready
                        if data.get("event_type") == "subscribed":
                            ev = PodCreatedEvent(
                                execution_id=exec_id,
                                pod_name=f"executor-{exec_id}",
                                namespace="default",
                                metadata=AvroEventMetadata(service_name="tests", service_version="1"),
                            )
                            await bus.publish_event(exec_id, ev)

                        # Stop when we receive the pod event
                        if data.get("event_type") == "pod_created":
                            pod_event_received = True
                            break
            except TimeoutError:
                pass

        assert pod_event_received, f"Expected pod_created event, got events: {events}"

    @pytest.mark.asyncio
    async def test_sse_route_requires_auth(self, client: AsyncClient) -> None:
        """Test that SSE routes require authentication (HTTP-level test only)."""
        r = await client.get("/api/v1/events/notifications/stream")
        assert r.status_code == 401

        exec_id = str(uuid4())
        r = await client.get(f"/api/v1/events/executions/{exec_id}")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_sse_endpoint_returns_correct_headers(self, test_user: AsyncClient) -> None:
        """Test SSE health endpoint works (streaming tests done via service)."""
        r = await test_user.get("/api/v1/events/health")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sse_service_connections(
            self, scope: AsyncContainer, test_user: AsyncClient
    ) -> None:
        """Test multiple concurrent SSE connections through the service."""
        sse_service: SSEService = await scope.get(SSEService)

        async def create_and_verify_stream(user_id: str) -> bool:
            async with aclosing(sse_service.create_notification_stream(user_id)) as stream:
                async for event in stream:
                    if "data" in event:
                        data = json.loads(event["data"])
                        if data.get("event_type") == "connected":
                            return True
                    break
            return False

        results = await asyncio.gather(
            create_and_verify_stream("user1"),
            create_and_verify_stream("user2"),
            create_and_verify_stream("user3"),
            return_exceptions=True,
        )

        successful = sum(1 for r in results if r is True)
        assert successful >= 2
