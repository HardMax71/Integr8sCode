"""Behavioral tests for app/api/rate_limit.check_rate_limit."""

import pytest
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from app.api.rate_limit import check_rate_limit, DynamicRateLimiter
from app.domain.rate_limit.rate_limit_models import RateLimitStatus, RateLimitAlgorithm
from app.schemas_pydantic.user import User
from app.domain.enums.user import UserRole


class FakeRateLimitService:
    def __init__(self, status: RateLimitStatus):
        self._status = status

    async def check_rate_limit(self, user_id: str, endpoint: str, username: str | None):  # noqa: ANN001
        self._last = (user_id, endpoint, username)
        return self._status


def _make_request(path: str = "/api/test"):
    # Provide a minimal object that mimics FastAPI Request relevant parts
    # and includes a dummy Dishka container to satisfy @inject wrapper.
    state = SimpleNamespace()

    class DummyContainer:
        def __init__(self, state):
            self._state = state

        async def get(self, _type, component=None):  # noqa: ANN001
            # Return the injected fake service set by the test
            return getattr(self._state, "_svc", None)

    state.dishka_container = DummyContainer(state)
    # Minimal headers/client to satisfy get_client_ip
    headers = {}
    client = SimpleNamespace(host="127.0.0.1")
    return SimpleNamespace(url=SimpleNamespace(path=path), state=state, headers=headers, client=client)


@pytest.mark.asyncio
async def test_dynamic_rate_limiter_alias():
    assert DynamicRateLimiter is check_rate_limit


@pytest.mark.asyncio
async def test_check_rate_limit_authenticated_allows_and_sets_headers():
    status = RateLimitStatus(
        allowed=True,
        limit=100,
        remaining=75,
        reset_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        retry_after=None,
        matched_rule=None,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    )
    svc = FakeRateLimitService(status)
    req = _make_request("/api/endpoint")
    # Provide the service instance to the dummy container
    req.state._svc = svc
    user = User(
        user_id="user_123",
        username="alice",
        email="a@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    await check_rate_limit(request=req, current_user=user)

    # Assert headers set on request state
    hdrs = req.state.rate_limit_headers
    assert hdrs["X-RateLimit-Limit"] == str(status.limit)
    assert hdrs["X-RateLimit-Remaining"] == str(status.remaining)
    assert hdrs["X-RateLimit-Reset"].isdigit()
    assert hdrs["X-RateLimit-Algorithm"] == status.algorithm


@pytest.mark.asyncio
async def test_check_rate_limit_anonymous_applies_multiplier():
    status = RateLimitStatus(
        allowed=True,
        limit=100,
        remaining=80,
        reset_at=datetime.now(timezone.utc) + timedelta(seconds=120),
        retry_after=None,
        matched_rule=None,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    svc = FakeRateLimitService(status)
    req = _make_request("/api/endpoint")
    req.state._svc = svc

    await check_rate_limit(request=req, current_user=None)

    hdrs = req.state.rate_limit_headers
    # Anonymous users get 50% of limit
    assert hdrs["X-RateLimit-Limit"] == str(50)
    # Remaining is clamped to new limit
    assert hdrs["X-RateLimit-Remaining"] == str(50)


@pytest.mark.asyncio
async def test_check_rate_limit_denied_raises_http_429_with_headers():
    reset_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    status = RateLimitStatus(
        allowed=False,
        limit=10,
        remaining=0,
        reset_at=reset_at,
        retry_after=15,
        matched_rule=None,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    svc = FakeRateLimitService(status)
    req = _make_request("/api/endpoint")
    req.state._svc = svc

    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(request=req, current_user=None)

    e = exc.value
    assert e.status_code == 429
    assert isinstance(e.detail, dict)
    assert e.detail["message"] == "Rate limit exceeded"
    assert e.detail["limit"] == 5
    assert e.headers["X-RateLimit-Limit"] == "5"
    assert e.headers["X-RateLimit-Remaining"] == "0"
    assert e.headers["Retry-After"] == "15"
