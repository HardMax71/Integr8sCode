import asyncio
from typing import Any

import pytest
import pytest_asyncio
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from async_asgi_testclient import TestClient as SSETestClient
from fastapi import FastAPI
from httpx import AsyncClient

from tests.e2e.conftest import EventWaiter

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
    for name, value in test_user.cookies.items():
        client.cookie_jar[name] = value
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
    async def test_notification_stream_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Notification stream requires authentication."""
        response = await client.get("/api/v1/events/notifications/stream")
        assert response.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.kafka
    async def test_notification_stream_returns_event_stream(
        self,
        sse_client: SSETestClient,
        test_user: AsyncClient,
        simple_execution_request: ExecutionRequest,
        event_waiter: EventWaiter,
    ) -> None:
        """Notification stream returns SSE content type when a notification arrives.

        The notification stream has no initial control events (unlike the
        execution stream). async-asgi-testclient blocks until the first
        http.response.body ASGI message. We trigger a real notification by
        creating an execution and waiting for its result — the notification
        handler publishes to Redis before RESULT_STORED, unblocking the stream.
        """
        async with sse_client:
            # Start stream in background — blocks until first body chunk
            stream_task = asyncio.create_task(
                sse_client.get(
                    "/api/v1/events/notifications/stream", stream=True
                )
            )
            # Allow Redis subscription to establish
            await asyncio.sleep(0.5)

            # Trigger a notification: execution → result → notification
            resp = await test_user.post(
                "/api/v1/execute",
                json=simple_execution_request.model_dump(),
            )
            assert resp.status_code == 200
            execution = ExecutionResponse.model_validate(resp.json())
            await event_waiter.wait_for_result(execution.execution_id)

            # Notification published to Redis unblocks the SSE stream
            response = await asyncio.wait_for(stream_task, timeout=10.0)

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            body = response.raw.read().decode("utf-8")
            assert len(body) > 0


class TestExecutionStream:
    """Tests for GET /api/v1/events/executions/{execution_id}."""

    @pytest.mark.asyncio
    async def test_execution_stream_returns_event_stream(
        self, sse_client: SSETestClient, created_execution: ExecutionResponse
    ) -> None:
        """Execution stream returns SSE content type and first body chunk.

        async-asgi-testclient waits for the first http.response.body ASGI
        message before returning the response object. For execution streams
        this is the ``status`` control event, confirming the SSE generator
        started and yielded data.
        """
        async with sse_client:
            response = await sse_client.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            # The first body chunk (buffered by async-asgi-testclient during
            # response construction) contains the ``status`` SSE event.
            first_chunk = response.raw.read()
            body = first_chunk.decode("utf-8")
            assert "status" in body
            assert created_execution.execution_id in body

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
        """Another user's execution stream still opens (auth at event level).

        SSE endpoints return 200 and start streaming. The status control event
        is always sent; business events are filtered by ownership.
        """
        async with sse_client_another:
            response = await sse_client_another.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            # Another user still receives the initial status event
            first_chunk = response.raw.read()
            assert b"status" in first_chunk
