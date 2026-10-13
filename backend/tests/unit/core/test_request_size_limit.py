import json

import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.types import Message

from app.core.exceptions import configure_exception_handlers
from app.core.middlewares import RequestSizeLimitMiddleware

pytestmark = pytest.mark.unit

_MB = 1024 * 1024


class _Payload(BaseModel):
    data: str


async def _echo(payload: _Payload) -> dict[str, int]:
    return {"size": len(payload.data)}


def _app() -> RequestSizeLimitMiddleware:
    api = FastAPI()
    configure_exception_handlers(api)
    api.add_api_route("/echo", _echo, methods=["POST"])
    return RequestSizeLimitMiddleware(api, max_size_mb=1)


class _Channel:
    """Feeds the request body in chunks and keeps every message the app sends back."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.pending: list[Message] = [
            {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1} for i, chunk in enumerate(chunks)
        ]
        self.sent: list[Message] = []

    async def receive(self) -> Message:
        return self.pending.pop(0) if self.pending else {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        self.sent.append(message)


async def _post(chunks: list[bytes], content_length: int | None) -> tuple[int, dict[str, object]]:
    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/echo",
        "raw_path": b"/echo",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("203.0.113.7", 50000),
        "server": ("test", 443),
    }
    channel = _Channel(chunks)
    await _app()(scope, channel.receive, channel.send)
    body = b"".join(m.get("body", b"") for m in channel.sent if m["type"] == "http.response.body")
    return int(channel.sent[0]["status"]), json.loads(body)


_TOO_LARGE = {"status": 413, "detail": "Request too large. Maximum size is 1.0MB"}


async def test_small_body_passes() -> None:
    body = json.dumps({"data": "x" * 10}).encode()
    assert await _post([body], len(body)) == (200, {"size": 10})


async def test_content_length_over_the_limit_is_rejected_before_reading() -> None:
    assert await _post([b"{}"], 2 * _MB) == (413, _TOO_LARGE)


async def test_streamed_body_over_the_limit_is_rejected() -> None:
    body = json.dumps({"data": "x" * (_MB + 10)}).encode()
    chunks = [body[i : i + 256 * 1024] for i in range(0, len(body), 256 * 1024)]
    assert await _post(chunks, None) == (413, _TOO_LARGE)
