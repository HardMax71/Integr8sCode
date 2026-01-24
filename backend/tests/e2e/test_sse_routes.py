import anyio
import pytest
from app.domain.enums.sse import SSEHealthStatus
from app.schemas_pydantic.execution import ExecutionResponse
from app.schemas_pydantic.sse import SSEHealthResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]

SSE_TIMEOUT_SECONDS = 5.0  # Timeout for SSE connection establishment


class TestSSEHealth:
    """Tests for GET /api/v1/events/health."""

    @pytest.mark.asyncio
    async def test_sse_health(self, test_user: AsyncClient) -> None:
        """Get SSE service health status."""
        response = await test_user.get("/api/v1/events/health")

        assert response.status_code == 200
        result = SSEHealthResponse.model_validate(response.json())

        assert result.status == SSEHealthStatus.HEALTHY
        assert isinstance(result.kafka_enabled, bool)
        assert result.active_connections >= 0
        assert result.active_executions >= 0
        assert result.active_consumers >= 0
        assert result.max_connections_per_user >= 0
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_sse_health_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """SSE health requires authentication."""
        response = await client.get("/api/v1/events/health")
        assert response.status_code == 401


class TestNotificationStream:
    """Tests for GET /api/v1/events/notifications/stream."""

    @pytest.mark.asyncio
    async def test_notification_stream_returns_event_stream(
            self, test_user: AsyncClient
    ) -> None:
        """Notification stream returns SSE content type."""
        with anyio.fail_after(SSE_TIMEOUT_SECONDS):
            async with test_user.stream(
                    "GET", "/api/v1/events/notifications/stream"
            ) as response:
                assert response.status_code == 200
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_notification_stream_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Notification stream requires authentication."""
        response = await client.get("/api/v1/events/notifications/stream")
        assert response.status_code == 401


class TestExecutionStream:
    """Tests for GET /api/v1/events/executions/{execution_id}."""

    @pytest.mark.asyncio
    async def test_execution_stream_returns_event_stream(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Execution events stream returns SSE content type."""
        with anyio.fail_after(SSE_TIMEOUT_SECONDS):
            async with test_user.stream(
                    "GET", f"/api/v1/events/executions/{created_execution.execution_id}"
            ) as response:
                assert response.status_code == 200
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_execution_stream_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Execution stream requires authentication."""
        response = await client.get("/api/v1/events/executions/some-id")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_execution_stream_other_users_execution(
            self, test_user: AsyncClient, another_user: AsyncClient,
            created_execution: ExecutionResponse
    ) -> None:
        """Streaming another user's execution opens but events are filtered."""
        # SSE endpoints return 200 and start streaming - authorization
        # happens at event level (user won't receive events for executions
        # they don't own). We verify the stream opens with correct content-type.
        with anyio.fail_after(SSE_TIMEOUT_SECONDS):
            async with another_user.stream(
                    "GET", f"/api/v1/events/executions/{created_execution.execution_id}"
            ) as response:
                assert response.status_code == 200
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type
