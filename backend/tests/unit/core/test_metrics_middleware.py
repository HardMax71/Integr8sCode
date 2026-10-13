import asyncio
from unittest.mock import MagicMock, call

import pytest
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.middlewares import MetricsMiddleware

pytestmark = pytest.mark.unit


async def _ok(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok", status_code=201)(scope, receive, send)


async def _boom(scope: Scope, receive: Receive, send: Send) -> None:
    raise RuntimeError("boom")


async def _cancelled(scope: Scope, receive: Receive, send: Send) -> None:
    raise asyncio.CancelledError


async def _fails_mid_stream(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    raise RuntimeError("boom")


def _middleware(app: ASGIApp) -> tuple[MetricsMiddleware, MagicMock, MagicMock, MagicMock]:
    middleware = MetricsMiddleware(app)
    counter, duration, active = MagicMock(), MagicMock(), MagicMock()
    middleware.request_counter = counter
    middleware.request_duration = duration
    middleware.request_size = MagicMock()
    middleware.response_size = MagicMock()
    middleware.active_requests = active
    return middleware, counter, duration, active


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: Message) -> None:
    return None


async def _call(middleware: MetricsMiddleware) -> None:
    scope: Scope = {"type": "http", "method": "GET", "path": "/api/v1/things/42", "headers": []}
    await middleware(scope, _receive, _send)


@pytest.mark.parametrize(
    ("app", "raises", "status"),
    [
        (_ok, None, "201"),
        (_boom, RuntimeError, "500"),
        (_cancelled, asyncio.CancelledError, "500"),
        (_fails_mid_stream, RuntimeError, "500"),
    ],
)
async def test_every_request_is_counted_and_released(
    app: ASGIApp, raises: type[BaseException] | None, status: str
) -> None:
    middleware, counter, duration, active = _middleware(app)

    if raises is None:
        await _call(middleware)
    else:
        with pytest.raises(raises):
            await _call(middleware)

    path = {"method": "GET", "path": "/api/v1/things/{id}"}
    assert active.add.call_args_list == [call(1, path), call(-1, path)]
    counter.add.assert_called_once_with(1, {**path, "status": status})
    duration.record.assert_called_once()
