from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from dishka import AsyncContainer
from starlette.responses import PlainTextResponse
from starlette.types import Message, Receive, Scope, Send

from app.core.metrics import SecurityMetrics
from app.core.middlewares import RateLimitMiddleware
from app.core.security import SecurityService
from app.domain.rate_limit import RateLimitStatus
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings

pytestmark = pytest.mark.unit


async def _ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


async def _request(middleware: RateLimitMiddleware, path: str, cookies: str = "") -> int:
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
        "headers": [(b"cookie", cookies.encode())],
        "client": ("203.0.113.7", 50000),
        "server": ("test", 443),
        "scheme": "https",
        "root_path": "",
        "http_version": "1.1",
    }
    await middleware(scope, receive, send)
    return int(messages[0]["status"])


def _rate_limit_service(allowed: bool) -> AsyncMock:
    service = AsyncMock(spec=RateLimitService)
    service.check_rate_limit.return_value = RateLimitStatus(
        allowed=allowed, limit=1, remaining=0, reset_at=datetime.now(timezone.utc), retry_after=30
    )
    return service


def _middleware(service: AsyncMock, security: SecurityService, settings: Settings) -> RateLimitMiddleware:
    services: dict[type, object] = {RateLimitService: service, SecurityService: security}
    container = AsyncMock(spec=AsyncContainer)
    container.get.side_effect = lambda dependency: services[dependency]
    enabled = settings.model_copy(update={"RATE_LIMIT_ENABLED": True})
    return RateLimitMiddleware(_ok_app, container=container, settings=enabled)


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
async def test_only_health_and_auth_routes_skip_rate_limiting(
    test_settings: Settings, security_metrics: SecurityMetrics, path: str, expected_status: int, checked: bool
) -> None:
    service = _rate_limit_service(allowed=False)
    middleware = _middleware(service, SecurityService(test_settings, security_metrics), test_settings)

    assert await _request(middleware, path) == expected_status
    assert service.check_rate_limit.await_count == int(checked)


async def test_a_valid_token_keys_the_request_by_user_id(
    test_settings: Settings, security_metrics: SecurityMetrics
) -> None:
    security = SecurityService(test_settings, security_metrics)
    token = security.create_access_token({"sub": "u", "user_id": "user-1"}, expires_delta=timedelta(minutes=5))
    service = _rate_limit_service(allowed=True)

    assert (
        await _request(_middleware(service, security, test_settings), "/api/v1/execute", f"access_token={token}") == 200
    )
    service.check_rate_limit.assert_awaited_once_with(user_id="user-1", endpoint="/api/v1/execute")


@pytest.mark.parametrize("cookies", ["access_token=forged.token.value", ""], ids=["forged_token", "anonymous"])
async def test_other_requests_are_keyed_by_client_ip(
    test_settings: Settings, security_metrics: SecurityMetrics, cookies: str
) -> None:
    service = _rate_limit_service(allowed=True)
    middleware = _middleware(service, SecurityService(test_settings, security_metrics), test_settings)

    assert await _request(middleware, "/api/v1/execute", cookies) == 200
    service.check_rate_limit.assert_awaited_once_with(user_id="ip:203.0.113.7", endpoint="/api/v1/execute")
