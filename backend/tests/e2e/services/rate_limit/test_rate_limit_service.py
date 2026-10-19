from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import redis.asyncio as redis
import structlog
from opentelemetry import trace

from app.domain.rate_limit import (
    EndpointGroup,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    UserRateLimit,
)
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings

pytestmark = [pytest.mark.e2e]


@pytest.fixture
async def svc(redis_client: redis.Redis, test_settings: Settings) -> RateLimitService:
    """A service of its own, so a test's config and counters live under a prefix no other test reads."""
    settings = test_settings.model_copy(update={"RATE_LIMIT_REDIS_PREFIX": f"rate_limit_test:{uuid4().hex}:"})
    return RateLimitService(redis_client, settings, trace.NoOpTracer(), structlog.get_logger("test"))


async def test_normalize_and_bypass_and_no_rule(svc: RateLimitService) -> None:

    # normalization masks uuids and ids
    n = svc._normalize_endpoint("/api/12345678901234567890/abcdef-1234-5678-9abc-def012345678")
    assert "*" in n

    # bypass user is always allowed
    cfg = RateLimitConfig(default_rules=[], user_overrides={"u1": UserRateLimit(user_id="u1", bypass_rate_limit=True)})
    await svc.update_config(cfg)
    res2 = await svc.check_rate_limit("u1", "/api/x")
    assert res2.allowed is True

    # no matching rule -> allowed
    await svc.update_config(RateLimitConfig(default_rules=[]))
    res3 = await svc.check_rate_limit("u2", "/none")
    assert res3.allowed is True


async def test_sliding_window_allowed_and_rejected(svc: RateLimitService) -> None:
    # matching rule with window 5, limit 3
    rule = RateLimitRule(
        endpoint_pattern=r"^/api/v1/x",
        group=EndpointGroup.API,
        requests=3,
        window_seconds=5,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    await svc.update_config(RateLimitConfig(default_rules=[rule]))

    # Make 3 requests - all should be allowed
    for i in range(3):
        ok = await svc.check_rate_limit("u", "/api/v1/x")
        assert ok.allowed is True, f"Request {i + 1} should be allowed"

    # 4th request should be rejected
    rej = await svc.check_rate_limit("u", "/api/v1/x")
    assert rej.allowed is False and rej.retry_after is not None

    # Provided config with global_enabled False
    await svc.update_config(RateLimitConfig(default_rules=[rule], global_enabled=False))
    res_disabled = await svc.check_rate_limit("u", "/api/v1/x")
    assert res_disabled.allowed is True


async def test_token_bucket_paths(svc: RateLimitService) -> None:
    rule = RateLimitRule(
        endpoint_pattern=r"^/api/v1/t",
        group=EndpointGroup.API,
        requests=2,
        window_seconds=10,
        burst_multiplier=1.0,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    )
    await svc.update_config(RateLimitConfig(default_rules=[rule]))

    # Make 2 requests - both should be allowed
    for i in range(2):
        ok = await svc.check_rate_limit("u", "/api/v1/t")
        assert ok.allowed is True, f"Request {i + 1} should be allowed"

    # 3rd request should be rejected (tokens exhausted)
    rej = await svc.check_rate_limit("u", "/api/v1/t")
    assert rej.allowed is False and rej.retry_after is not None

    # User multiplier applied; still allowed path
    cfg_mul = RateLimitConfig(
        default_rules=[
            RateLimitRule(
                endpoint_pattern=r"^/m",
                group=EndpointGroup.API,
                requests=2,
                window_seconds=10,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            )
        ],
        user_overrides={"u": UserRateLimit(user_id="u", global_multiplier=2.0)},
    )
    await svc.update_config(cfg_mul)
    ok_mul = await svc.check_rate_limit("u", "/m")
    assert ok_mul.allowed is True


async def test_config_update_and_user_helpers(svc: RateLimitService) -> None:
    cfg = RateLimitConfig(
        default_rules=[RateLimitRule(endpoint_pattern=r"^/a", group=EndpointGroup.API, requests=1, window_seconds=1)]
    )
    await svc.update_config(cfg)
    # _get_config from cache path
    got = await svc._get_config()
    assert got == cfg

    # Update user limit and read it back
    lim = UserRateLimit(user_id="u1", global_multiplier=2.0)
    await svc.update_user_rate_limit("u1", lim)
    assert await svc.get_user_rate_limit("u1") == lim

    # Reset and get usage stats via scan
    await svc.reset_user_limits("user")
    assert await svc.get_usage_stats("user") == {}


async def test_ip_based_rate_limiting(svc: RateLimitService) -> None:
    """Test IP-based rate limiting."""

    # Test IP-based check
    cfg = RateLimitConfig(
        default_rules=[RateLimitRule(endpoint_pattern=r"^/api", group=EndpointGroup.API, requests=5, window_seconds=60)]
    )
    await svc.update_config(cfg)

    # Check with IP identifier
    result = await svc.check_rate_limit("ip:192.168.1.1", "/api/test")
    assert result.allowed is True


async def test_get_config_roundtrip(svc: RateLimitService) -> None:
    cfg = RateLimitConfig(
        default_rules=[RateLimitRule(endpoint_pattern=r"^/z", group=EndpointGroup.API, requests=1, window_seconds=1)]
    )
    await svc.update_config(cfg)
    assert await svc._get_config() == cfg


async def test_sliding_window_edge(svc: RateLimitService) -> None:
    # Configure a tight window and ensure behavior is consistent
    cfg = RateLimitConfig(
        default_rules=[
            RateLimitRule(
                endpoint_pattern=r"^/edge",
                group=EndpointGroup.API,
                requests=1,
                window_seconds=60,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            )
        ]
    )
    await svc.update_config(cfg)
    ok = await svc.check_rate_limit("u", "/edge")
    assert ok.allowed is True
    # Second request should be rejected (limit is 1)
    rej = await svc.check_rate_limit("u", "/edge")
    assert rej.allowed is False


async def test_sliding_window_pipeline_failure(test_settings: Settings) -> None:
    client = AsyncMock(spec=redis.Redis)
    client.sadd = AsyncMock()
    client.pipeline = MagicMock()
    client.pipeline.return_value.execute = AsyncMock(side_effect=ConnectionError("Pipeline failed"))
    svc = RateLimitService(client, test_settings, trace.NoOpTracer(), structlog.get_logger("test"))
    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )

    with pytest.raises(ConnectionError):
        await svc._check_sliding_window("user1", "/api/test", int(rule.requests), rule.window_seconds, rule)


async def test_token_bucket_invalid_data(svc: RateLimitService) -> None:
    key = f"{svc.prefix}tb:user:/api"
    await svc.redis.set(key, "invalid-json")

    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    )

    status = await svc._check_token_bucket(
        "user", "/api", int(rule.requests), rule.window_seconds, rule.burst_multiplier or 1.0, rule
    )
    assert status.allowed is True


async def test_update_config_serialization_error(test_settings: Settings) -> None:
    client = AsyncMock(spec=redis.Redis)
    client.set.side_effect = ValueError("Serialization failed")
    svc = RateLimitService(client, test_settings, trace.NoOpTracer(), structlog.get_logger("test"))

    with pytest.raises(ValueError):
        await svc.update_config(RateLimitConfig(default_rules=[]))


async def test_user_without_override_gets_the_defaults(svc: RateLimitService) -> None:
    limit = await svc.get_user_rate_limit("nonexistent")
    assert (limit.user_id, limit.rules, limit.global_multiplier, limit.bypass_rate_limit) == (
        "nonexistent",
        [],
        1.0,
        False,
    )


async def test_reset_user_limits_error(test_settings: Settings) -> None:
    client = AsyncMock(spec=redis.Redis)
    client.smembers.side_effect = ConnectionError("smembers failed")
    svc = RateLimitService(client, test_settings, trace.NoOpTracer(), structlog.get_logger("test"))

    with pytest.raises(ConnectionError):
        await svc.reset_user_limits("user")


async def test_get_usage_stats_with_keys(svc: RateLimitService) -> None:
    user_id = f"user-{uuid4().hex[:8]}"
    index_key = f"{svc.prefix}index:{user_id}"
    sw_key = f"{svc.prefix}sw:{user_id}:/api:key1"
    await svc.redis.sadd(index_key, sw_key)
    stats = await svc.get_usage_stats(user_id)
    assert list(stats) == ["/api:key1"]


async def test_check_rate_limit_with_user_override(svc: RateLimitService) -> None:
    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=3,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    user_override = UserRateLimit(user_id="special_user", global_multiplier=4.0)
    await svc.update_config(RateLimitConfig(default_rules=[rule], user_overrides={"special_user": user_override}))

    # Normal user: exceed after limit
    endpoint = "/api/test"
    allowed_count = 0
    for _ in range(5):
        res = await svc.check_rate_limit("normal_user", endpoint)
        allowed_count += 1 if res.allowed else 0
    assert allowed_count == int(rule.requests)  # Should be exactly 3

    # Special user: higher multiplier allows more requests
    allowed_count_special = 0
    for _ in range(6):
        res = await svc.check_rate_limit("special_user", endpoint)
        allowed_count_special += 1 if res.allowed else 0
    assert allowed_count_special > allowed_count
