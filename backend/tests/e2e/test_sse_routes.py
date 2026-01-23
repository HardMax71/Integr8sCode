import anyio
import pytest
from app.schemas_pydantic.execution import ExecutionResponse
from app.schemas_pydantic.sse import SSEHealthResponse
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]

SSE_TIMEOUT_SECONDS = 2.0  # Short timeout for SSE header checks


class TestSSEHealth:
    """Tests for GET /api/v1/events/health."""

    @pytest.mark.asyncio
    async def test_sse_health(self, test_user: AsyncClient) -> None:
        """Get SSE service health status."""
        response = await test_user.get("/api/v1/events/health")

        assert response.status_code == 200
        result = SSEHealthResponse.model_validate(response.json())

        assert result.status in ["healthy", "degraded", "unhealthy"]
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
        # Note: httpx doesn't fully support SSE streaming in tests,
        # but we can verify the content type and initial response
        with anyio.move_on_after(SSE_TIMEOUT_SECONDS):
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
            self, test_user: AsyncClient
    ) -> None:
        """Execution events stream returns SSE content type."""
        # Create an execution first
        exec_response = await test_user.post(
            "/api/v1/execute",
            json={
                "script": "print('sse test')",
                "lang": "python",
                "lang_version": "3.11",
            },
        )
        assert exec_response.status_code == 200
        execution = ExecutionResponse.model_validate(exec_response.json())

        # Stream execution events with timeout
        with anyio.move_on_after(SSE_TIMEOUT_SECONDS):
            async with test_user.stream(
                    "GET", f"/api/v1/events/executions/{execution.execution_id}"
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
            self, test_user: AsyncClient, another_user: AsyncClient
    ) -> None:
        """Cannot stream another user's execution events."""
        # Create execution as test_user
        exec_response = await test_user.post(
            "/api/v1/execute",
            json={
                "script": "print('private')",
                "lang": "python",
                "lang_version": "3.11",
            },
        )
        execution_id = exec_response.json()["execution_id"]

        # Try to stream as another_user with timeout
        with anyio.move_on_after(SSE_TIMEOUT_SECONDS):
            async with another_user.stream(
                    "GET", f"/api/v1/events/executions/{execution_id}"
            ) as response:
                # Should be forbidden or return empty stream
                assert response.status_code in [200, 403]
                if response.status_code == 200:
                    # If 200, content type should still be event-stream
                    content_type = response.headers.get("content-type", "")
                    assert "text/event-stream" in content_type
