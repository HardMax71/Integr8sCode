from typing import Any

import pytest
import pytest_asyncio
from app.schemas_pydantic.execution import ExecutionResponse
from async_asgi_testclient import TestClient as SSETestClient
from fastapi import FastAPI
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]


class _NoLifespan:
    """ASGI wrapper that completes lifespan events immediately.

    async-asgi-testclient's context manager triggers ASGI lifespan
    startup/shutdown. Without this wrapper, the shutdown closes the
    Kafka broker that the session-scoped ``app`` fixture owns, breaking
    every subsequent test that publishes events.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            await receive()  # lifespan.startup
            await send({"type": "lifespan.startup.complete"})
            await receive()  # lifespan.shutdown
            await send({"type": "lifespan.shutdown.complete"})
            return
        await self.app(scope, receive, send)


@pytest_asyncio.fixture
async def sse_client(app: FastAPI, test_user: AsyncClient) -> SSETestClient:
    """SSE-capable test client with auth cookies from test_user.

    Uses async-asgi-testclient which properly streams SSE responses,
    unlike httpx's ASGITransport which buffers entire responses.
    See: https://github.com/encode/httpx/issues/2186

    The app is wrapped with _NoLifespan to prevent the SSE client's
    context manager from closing the session-scoped Kafka broker.
    """
    client = SSETestClient(_NoLifespan(app))
    # Copy auth cookies from httpx client (SimpleCookie uses dict-style assignment)
    for name, value in test_user.cookies.items():
        client.cookie_jar[name] = value
    # Copy CSRF header
    if csrf := test_user.headers.get("X-CSRF-Token"):
        client.headers["X-CSRF-Token"] = csrf
    return client


@pytest_asyncio.fixture
async def sse_client_another(app: FastAPI, another_user: AsyncClient) -> SSETestClient:
    """SSE-capable test client with auth from another_user."""
    client = SSETestClient(_NoLifespan(app))
    for name, value in another_user.cookies.items():
        client.cookie_jar[name] = value
    if csrf := another_user.headers.get("X-CSRF-Token"):
        client.headers["X-CSRF-Token"] = csrf
    return client


class TestNotificationStream:
    """Tests for GET /api/v1/events/notifications/stream."""

    @pytest.mark.asyncio
    async def test_notification_stream_returns_event_stream(
        self, sse_client: SSETestClient
    ) -> None:
        """Notification stream returns SSE content type and streams data."""
        async with sse_client:
            response = await sse_client.get(
                "/api/v1/events/notifications/stream", stream=True
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

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
        self, sse_client: SSETestClient, created_execution: ExecutionResponse
    ) -> None:
        """Execution events stream returns SSE content type."""
        async with sse_client:
            response = await sse_client.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_execution_stream_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Execution stream requires authentication."""
        response = await client.get("/api/v1/events/executions/some-id")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_execution_stream_other_users_execution(
        self,
        sse_client_another: SSETestClient,
        created_execution: ExecutionResponse,
    ) -> None:
        """Streaming another user's execution opens but events are filtered.

        SSE endpoints return 200 and start streaming - authorization
        happens at event level (user won't receive events for executions
        they don't own). We verify the stream opens with correct content-type.
        """
        async with sse_client_another:
            response = await sse_client_another.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
