import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from app.domain.enums.sse import SSEControlEvent
from app.schemas_pydantic.execution import ExecutionResponse
from async_asgi_testclient import TestClient as SSETestClient
from fastapi import FastAPI
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]



@dataclass
class SSEEvent:
    """Parsed SSE event."""

    event: str = "message"
    data: str = ""
    id: str = ""
    retry: int | None = None

    def json(self) -> Any:
        return json.loads(self.data)


def _parse_sse_event(raw: str) -> SSEEvent | None:
    """Parse a single SSE event block (text between double-newlines)."""
    ev = SSEEvent()
    data_lines: list[str] = []
    has_data = False

    for line in raw.split("\n"):
        line = line.rstrip("\r")
        if not line or line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.lstrip(" ")  # SSE spec: strip one leading space
        if name == "event":
            ev.event = value
        elif name == "data":
            has_data = True
            data_lines.append(value)
        elif name == "id":
            ev.id = value
        elif name == "retry":
            with contextlib.suppress(ValueError):
                ev.retry = int(value)

    if not has_data:
        return None
    ev.data = "\n".join(data_lines)
    return ev


async def collect_sse_events(
    response: Any,
    *,
    max_events: int = 10,
    timeout: float = 10.0,
) -> list[SSEEvent]:
    """Read SSE events from an async-asgi-testclient streaming response.

    Stops after *max_events* data-bearing events or *timeout* seconds.
    """
    events: list[SSEEvent] = []
    buf = ""

    async with asyncio.timeout(timeout):
        async for chunk in response.iter_content(512):
            buf += chunk.decode("utf-8")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev = _parse_sse_event(block)
                if ev is not None:
                    events.append(ev)
            if len(events) >= max_events:
                break

    return events



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
        """Notification stream returns SSE content type."""
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
        """Execution stream returns SSE content type."""
        async with sse_client:
            response = await sse_client.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_execution_stream_yields_control_events(
        self, sse_client: SSETestClient, created_execution: ExecutionResponse
    ) -> None:
        """Execution stream yields connected/subscribed/status control events."""
        async with sse_client:
            response = await sse_client.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )
            assert response.status_code == 200

            # The server yields connected + subscribed immediately, then status
            # after a DB lookup. Collect up to 3 events with a generous timeout.
            events = await collect_sse_events(response, max_events=3, timeout=10.0)

            assert len(events) >= 2, f"Expected >= 2 control events, got {len(events)}"

            # First event: connected
            connected = events[0].json()
            assert connected["event_type"] == SSEControlEvent.CONNECTED
            assert connected["execution_id"] == created_execution.execution_id

            # Second event: subscribed
            subscribed = events[1].json()
            assert subscribed["event_type"] == SSEControlEvent.SUBSCRIBED
            assert subscribed["execution_id"] == created_execution.execution_id
            assert subscribed["message"] == "Redis subscription established"

            # Third event (if present): status with current execution state
            if len(events) >= 3:
                status_ev = events[2].json()
                assert status_ev["event_type"] == SSEControlEvent.STATUS
                assert status_ev["execution_id"] == created_execution.execution_id
                assert status_ev["status"] is not None

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

        SSE endpoints return 200 and start streaming. The connected/subscribed
        control events are always sent; business events are filtered by ownership.
        """
        async with sse_client_another:
            response = await sse_client_another.get(
                f"/api/v1/events/executions/{created_execution.execution_id}",
                stream=True,
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            # Even another user receives control events (connected, subscribed)
            events = await collect_sse_events(response, max_events=2, timeout=10.0)
            assert len(events) >= 2
            assert events[0].json()["event_type"] == SSEControlEvent.CONNECTED
            assert events[1].json()["event_type"] == SSEControlEvent.SUBSCRIBED
