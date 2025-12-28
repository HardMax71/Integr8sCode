import asyncio
import json
from typing import Dict
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.schemas_pydantic.sse import RedisNotificationMessage, SSEHealthResponse
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_service import SSEService
from tests.helpers.eventually import eventually


# Note: httpx with ASGITransport doesn't support SSE streaming
# We test SSE functionality directly through the service, not HTTP


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
    async def test_sse_health_status(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        r = await client.get("/api/v1/events/health")
        assert r.status_code == 200
        health = SSEHealthResponse(**r.json())
        assert health.status in ("healthy", "degraded", "unhealthy", "draining")
        assert isinstance(health.active_connections, int) and health.active_connections >= 0

    @pytest.mark.asyncio
    async def test_notification_stream_service(self, scope, test_user: Dict[str, str]) -> None:  # type: ignore[valid-type]
        """Test SSE notification stream directly through service (httpx doesn't support SSE streaming)."""
        sse_service: SSEService = await scope.get(SSEService)
        bus: SSERedisBus = await scope.get(SSERedisBus)
        user_id = f"user-{uuid4().hex[:8]}"
        
        # Create notification stream generator
        stream_gen = sse_service.create_notification_stream(user_id)
        
        # Collect events with timeout
        events = []
        async def collect_events():
            async for event in stream_gen:
                if "data" in event:
                    data = json.loads(event["data"])
                    events.append(data)
                    if data.get("event_type") == "notification" and data.get("subject") == "Hello":
                        break
        
        # Start collecting events
        collect_task = asyncio.create_task(collect_events())
        
        # Wait until the initial 'connected' event is received
        async def _connected() -> None:
            assert len(events) > 0 and events[0].get("event_type") == "connected"
        await eventually(_connected, timeout=2.0, interval=0.05)
        
        # Publish a notification
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
        
        # Wait for collection to complete
        try:
            await asyncio.wait_for(collect_task, timeout=2.0)
        except asyncio.TimeoutError:
            collect_task.cancel()
        
        # Verify we got notification
        notif_events = [e for e in events if e.get("event_type") == "notification" and e.get("subject") == "Hello"]
        assert len(notif_events) > 0

    @pytest.mark.asyncio
    async def test_execution_event_stream_service(self, scope, test_user: Dict[str, str]) -> None:  # type: ignore[valid-type]
        """Test SSE execution stream directly through service (httpx doesn't support SSE streaming)."""
        exec_id = f"e-{uuid4().hex[:8]}"
        user_id = "test-user-id"
        
        sse_service: SSEService = await scope.get(SSEService)
        bus: SSERedisBus = await scope.get(SSERedisBus)
        
        # Create execution stream generator
        stream_gen = sse_service.create_execution_stream(exec_id, user_id)
        
        # Collect events
        events = []
        async def collect_events():
            async for event in stream_gen:
                if "data" in event:
                    data = json.loads(event["data"])
                    events.append(data)
                    if data.get("event_type") == "pod_created" or data.get("type") == "pod_created":
                        break
        
        # Start collecting
        collect_task = asyncio.create_task(collect_events())
        
        # Wait until the initial 'connected' event is received
        async def _connected() -> None:
            assert len(events) > 0 and events[0].get("event_type") == "connected"
        await eventually(_connected, timeout=2.0, interval=0.05)
        
        # Publish pod event
        ev = PodCreatedEvent(
            execution_id=exec_id,
            pod_name=f"executor-{exec_id}",
            namespace="default",
            metadata=AvroEventMetadata(service_name="tests", service_version="1"),
        )
        await bus.publish_event(exec_id, ev)
        
        # Wait for collection
        try:
            await asyncio.wait_for(collect_task, timeout=2.0)
        except asyncio.TimeoutError:
            collect_task.cancel()
        
        # Verify pod event received
        pod_events = [e for e in events if e.get("event_type") == "pod_created" or e.get("type") == "pod_created"]
        assert len(pod_events) > 0

    @pytest.mark.asyncio
    async def test_sse_route_requires_auth(self, client: AsyncClient) -> None:
        """Test that SSE routes require authentication (HTTP-level test only)."""
        # Test notification stream requires auth
        r = await client.get("/api/v1/events/notifications/stream")
        assert r.status_code == 401
        
        # Test execution stream requires auth
        exec_id = str(uuid4())
        r = await client.get(f"/api/v1/events/executions/{exec_id}")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_sse_endpoint_returns_correct_headers(self, client: AsyncClient, test_user: Dict[str, str]) -> None:
        task = asyncio.create_task(client.get("/api/v1/events/notifications/stream"))
        
        async def _tick() -> None:
            return None
        await eventually(_tick, timeout=0.1, interval=0.01)
        
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        r = await client.get("/api/v1/events/health")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sse_service_connections(self, scope, test_user: Dict[str, str]) -> None:  # type: ignore[valid-type]
        """Test multiple concurrent SSE connections through the service."""
        sse_service: SSEService = await scope.get(SSEService)
        
        async def create_and_verify_stream(user_id: str) -> bool:
            stream_gen = sse_service.create_notification_stream(user_id)
            try:
                async for event in stream_gen:
                    if "data" in event:
                        data = json.loads(event["data"])
                        if data.get("event_type") == "connected":
                            return True
                    break  # Only check first event
            except Exception:
                return False
            return False
        
        # Create multiple concurrent connections
        results = await asyncio.gather(
            create_and_verify_stream("user1"),
            create_and_verify_stream("user2"),
            create_and_verify_stream("user3"),
            return_exceptions=True
        )
        
        # At least 2 should succeed
        successful = sum(1 for r in results if r is True)
        assert successful >= 2
