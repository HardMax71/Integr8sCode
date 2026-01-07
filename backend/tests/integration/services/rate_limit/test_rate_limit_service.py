import json
from collections.abc import Callable
from typing import Any, Self

import pytest
from app.domain.rate_limit import (
    EndpointGroup,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    UserRateLimit,
)
from app.services.rate_limit_service import RateLimitService
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.redis]


@pytest.mark.asyncio
async def test_normalize_and_disabled_and_bypass_and_no_rule(
    scope: AsyncContainer, unique_id: Callable[[str], str]
) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"
    # ensure disabled for first path
    await svc.update_config(RateLimitConfig(default_rules=[]))
    svc.settings.RATE_LIMIT_ENABLED = False
    # normalization masks uuids and ids
    n = svc._normalize_endpoint("/api/12345678901234567890/abcdef-1234-5678-9abc-def012345678")
    assert "*" in n
    # disabled path allowed
    res = await svc.check_rate_limit("u1", "/api/x")
    assert res.allowed is True

    # enabled, bypass
    svc.settings.RATE_LIMIT_ENABLED = True
    cfg = RateLimitConfig(default_rules=[], user_overrides={
        "u1": UserRateLimit(user_id="u1", bypass_rate_limit=True)
    })
    await svc.update_config(cfg)
    res2 = await svc.check_rate_limit("u1", "/api/x", config=None)
    assert res2.allowed is True

    # no matching rule -> allowed
    await svc.update_config(RateLimitConfig(default_rules=[]))
    res3 = await svc.check_rate_limit("u2", "/none")
    assert res3.allowed is True


@pytest.mark.asyncio
async def test_sliding_window_allowed_and_rejected(
    scope: AsyncContainer, unique_id: Callable[[str], str]
) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"
    svc.settings.RATE_LIMIT_ENABLED = True  # Enable rate limiting for this test
    # matching rule with window 5, limit 3
    rule = RateLimitRule(endpoint_pattern=r"^/api/v1/x", group=EndpointGroup.API, requests=3, window_seconds=5,
                         algorithm=RateLimitAlgorithm.SLIDING_WINDOW)
    await svc.update_config(RateLimitConfig(default_rules=[rule]))
    
    # Make 3 requests - all should be allowed
    for i in range(3):
        ok = await svc.check_rate_limit("u", "/api/v1/x")
        assert ok.allowed is True, f"Request {i+1} should be allowed"

    # 4th request should be rejected
    rej = await svc.check_rate_limit("u", "/api/v1/x")
    assert rej.allowed is False and rej.retry_after is not None

    # Provided config with global_enabled False
    cfg3 = RateLimitConfig(default_rules=[rule], global_enabled=False)
    res_disabled = await svc.check_rate_limit("u", "/api/v1/x", config=cfg3)
    assert res_disabled.allowed is True


@pytest.mark.asyncio
async def test_token_bucket_paths(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"
    svc.settings.RATE_LIMIT_ENABLED = True  # Enable rate limiting for this test
    rule = RateLimitRule(endpoint_pattern=r"^/api/v1/t", group=EndpointGroup.API, requests=2, window_seconds=10,
                         burst_multiplier=1.0, algorithm=RateLimitAlgorithm.TOKEN_BUCKET)
    await svc.update_config(RateLimitConfig(default_rules=[rule]))
    
    # Make 2 requests - both should be allowed
    for i in range(2):
        ok = await svc.check_rate_limit("u", "/api/v1/t")
        assert ok.allowed is True, f"Request {i+1} should be allowed"

    # 3rd request should be rejected (tokens exhausted)
    rej = await svc.check_rate_limit("u", "/api/v1/t")
    assert rej.allowed is False and rej.retry_after is not None

    # User multiplier applied; still allowed path
    cfg_mul = RateLimitConfig(default_rules=[
        RateLimitRule(endpoint_pattern=r"^/m", group=EndpointGroup.API, requests=2, window_seconds=10,
                      algorithm=RateLimitAlgorithm.SLIDING_WINDOW)],
                              user_overrides={"u": UserRateLimit(user_id="u", global_multiplier=2.0)})
    await svc.update_config(cfg_mul)
    ok_mul = await svc.check_rate_limit("u", "/m")
    assert ok_mul.allowed is True


@pytest.mark.asyncio
async def test_config_update_and_user_helpers(
    scope: AsyncContainer, unique_id: Callable[[str], str]
) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"
    cfg = RateLimitConfig(
        default_rules=[RateLimitRule(endpoint_pattern=r"^/a", group=EndpointGroup.API, requests=1, window_seconds=1)])
    await svc.update_config(cfg)
    # _get_config from cache path
    got = await svc._get_config()
    assert isinstance(got, RateLimitConfig)

    # Update user limit and read it back
    lim = UserRateLimit(user_id="u1")
    await svc.update_user_rate_limit("u1", lim)
    got_user = await svc.get_user_rate_limit("u1")
    assert got_user is not None

    # Reset and get usage stats via scan
    await svc.reset_user_limits("user")
    stats = await svc.get_usage_stats("user")
    assert isinstance(stats, dict)


@pytest.mark.asyncio
async def test_ip_based_rate_limiting(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    """Test IP-based rate limiting."""
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"

    # Test IP-based check
    cfg = RateLimitConfig(
        default_rules=[
            RateLimitRule(
                endpoint_pattern=r"^/api",
                group=EndpointGroup.API,
                requests=5,
                window_seconds=60
            )
        ]
    )
    await svc.update_config(cfg)

    # Check with IP identifier
    result = await svc.check_rate_limit("ip:192.168.1.1", "/api/test")
    assert result.allowed is True

    # Verify metrics object has requests_total counter for checks
    assert hasattr(svc.metrics, 'requests_total')


@pytest.mark.asyncio
async def test_get_config_roundtrip(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"
    rule = RateLimitRule(endpoint_pattern=r"^/z", group=EndpointGroup.API, requests=1, window_seconds=1)
    cfg = RateLimitConfig(default_rules=[rule])
    await svc.update_config(cfg)
    got = await svc._get_config()
    assert isinstance(got, RateLimitConfig)


@pytest.mark.asyncio
async def test_sliding_window_edge(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"
    svc.settings.RATE_LIMIT_ENABLED = True  # Enable rate limiting for this test
    # Configure a tight window and ensure behavior is consistent
    rule = RateLimitRule(
        endpoint_pattern=r"^/edge", group=EndpointGroup.API,
        requests=1, window_seconds=1, algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    cfg = RateLimitConfig(default_rules=[rule])
    await svc.update_config(cfg)
    ok = await svc.check_rate_limit("u", "/edge")
    assert ok.allowed is True
    # Second request should be rejected (limit is 1)
    rej = await svc.check_rate_limit("u", "/edge")
    assert rej.allowed is False


@pytest.mark.asyncio
async def test_sliding_window_pipeline_failure(
    scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch, unique_id: Callable[[str], str]
) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.prefix = f"{svc.prefix}{unique_id('')}:"

    class FailingPipe:
        def zremrangebyscore(self, *a: Any, **k: Any) -> Self: return self
        def zadd(self, *a: Any, **k: Any) -> Self: return self
        def zcard(self, *a: Any, **k: Any) -> Self: return self
        def expire(self, *a: Any, **k: Any) -> Self: return self
        async def execute(self) -> None: raise ConnectionError("Pipeline failed")

    monkeypatch.setattr(svc.redis, "pipeline", lambda: FailingPipe())

    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )

    with pytest.raises(ConnectionError):
        await svc._check_sliding_window(
            "user1", "/api/test", int(rule.requests), rule.window_seconds, rule
        )


@pytest.mark.asyncio
async def test_token_bucket_invalid_data(scope: AsyncContainer) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    key = f"{svc.prefix}tb:user:/api"
    await svc.redis.set(key, "invalid-json")

    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    )

    with pytest.raises(json.JSONDecodeError):
        await svc._check_token_bucket(
            "user", "/api", int(rule.requests), rule.window_seconds, rule.burst_multiplier or 1.0, rule
        )


@pytest.mark.asyncio
async def test_update_config_serialization_error(
    scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)

    async def failing_setex(key: str, ttl: int, value: str) -> None:
        raise ValueError("Serialization failed")
    monkeypatch.setattr(svc.redis, "setex", failing_setex)

    cfg = RateLimitConfig(default_rules=[])
    with pytest.raises(ValueError):
        await svc.update_config(cfg)


@pytest.mark.asyncio
async def test_get_user_rate_limit_not_found(scope: AsyncContainer) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    result = await svc.get_user_rate_limit("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_reset_user_limits_error(scope: AsyncContainer, monkeypatch: pytest.MonkeyPatch) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)

    async def failing_smembers(key: str) -> None:
        raise ConnectionError("smembers failed")
    monkeypatch.setattr(svc.redis, "smembers", failing_smembers)
    with pytest.raises(ConnectionError):
        await svc.reset_user_limits("user")


@pytest.mark.asyncio
async def test_get_usage_stats_with_keys(scope: AsyncContainer) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    user_id = "user"
    sw_key = f"{svc.prefix}sw:{user_id}:/api:key1"
    await svc._register_user_key(user_id, sw_key)
    stats = await svc.get_usage_stats(user_id)
    assert isinstance(stats, dict)


@pytest.mark.asyncio
async def test_check_rate_limit_with_user_override(scope: AsyncContainer) -> None:
    svc: RateLimitService = await scope.get(RateLimitService)
    svc.settings.RATE_LIMIT_ENABLED = True  # Enable rate limiting for this test
    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=3,
        window_seconds=2,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    user_override = UserRateLimit(user_id="special_user", global_multiplier=4.0)
    cfg = RateLimitConfig(default_rules=[rule], user_overrides={"special_user": user_override})

    # Normal user: exceed after limit
    endpoint = "/api/test"
    allowed_count = 0
    for _ in range(5):
        if (await svc.check_rate_limit("normal_user", endpoint, config=cfg)).allowed:
            allowed_count += 1
    assert allowed_count == int(rule.requests)  # Should be exactly 3

    # Special user: higher multiplier allows more requests
    allowed_count_special = 0
    for _ in range(6):
        if (await svc.check_rate_limit("special_user", endpoint, config=cfg)).allowed:
            allowed_count_special += 1
    assert allowed_count_special > allowed_count
