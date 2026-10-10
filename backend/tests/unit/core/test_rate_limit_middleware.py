from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from app.core.middlewares import RateLimitMiddleware
from app.domain.rate_limit import RateLimitStatus
from app.services.rate_limit_service import RateLimitService
from starlette.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send

pytestmark = pytest.mark.unit


async def _ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


async def _request(middleware: RateLimitMiddleware, path: str) -> int:
    messages: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("203.0.113.7", 50000),
        "server": ("test", 443),
        "scheme": "https",
        "root_path": "",
        "http_version": "1.1",
    }
    await middleware(scope, receive, send)
    return int(messages[0]["status"])


@pytest.mark.parametrize(
    ("path", "expected_status", "checked"),
    [
        ("/api/v1/health/live", 200, False),
        ("/api/v1/auth/login", 200, False),
        ("/api/v1/execute", 429, True),
        ("/health", 429, True),
        ("/metrics", 429, True),
    ],
)
async def test_only_health_and_auth_routes_skip_rate_limiting(path: str, expected_status: int, checked: bool) -> None:
    service = AsyncMock(spec=RateLimitService)
    service.check_rate_limit.return_value = RateLimitStatus(
        allowed=False,
        limit=1,
        remaining=0,
        reset_at=datetime.now(timezone.utc),
        retry_after=30,
    )
    middleware = RateLimitMiddleware(_ok_app, rate_limit_service=service)

    assert await _request(middleware, path) == expected_status
    assert service.check_rate_limit.await_count == int(checked)
