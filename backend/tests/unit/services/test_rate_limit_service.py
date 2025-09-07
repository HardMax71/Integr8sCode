import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.metrics.rate_limit import RateLimitMetrics
from app.domain.rate_limit import (
    EndpointGroup,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    UserRateLimit,
)
from app.services.rate_limit_service import RateLimitService


class FakePipe:
    def __init__(self, count: int):
        self.count = count
    def zremrangebyscore(self, *a, **k): return self
    def zadd(self, *a, **k): return self
    def zcard(self, *a, **k): return self
    def expire(self, *a, **k): return self
    async def execute(self): return [None, None, self.count, None]


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.count = 0
        self.oldest = datetime.now(timezone.utc).timestamp()
        self.scans = [
            (1, [b"rl:sw:user:/api:v1:x", b"rl:tb:user:/api:v1:y"]),
            (0, []),
        ]
    def pipeline(self): return FakePipe(self.count)
    async def get(self, key): return self.store.get(key)
    async def setex(self, key, ttl, value): self.store[key] = value  # noqa: ARG002
    async def zrange(self, key, *_a, **_k): return [[b"t", self.oldest]]  # noqa: ARG002
    async def zcard(self, key): return 3
    async def scan(self, cursor, match=None, count=100):  # noqa: ARG002
        return self.scans.pop(0) if self.scans else (0, [])
    async def delete(self, *keys):
        for k in keys: self.store.pop(k, None)


def make_service(redis_client: FakeRedis, enabled: bool = True) -> RateLimitService:
    settings = SimpleNamespace(RATE_LIMIT_REDIS_PREFIX="rl:", RATE_LIMIT_ENABLED=enabled)
    metrics = RateLimitMetrics()
    svc = RateLimitService(redis_client, settings, metrics)
    return svc


@pytest.mark.asyncio
async def test_normalize_and_disabled_and_bypass_and_no_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    r = FakeRedis(); r.count = 0; r.oldest = time_now = datetime.now(timezone.utc).timestamp()
    svc = make_service(r, enabled=False)
    # normalization masks uuids and ids
    n = svc._normalize_endpoint("/api/12345678901234567890/abcdef-1234-5678-9abc-def012345678")
    assert "*" in n
    # disabled path allowed
    res = await svc.check_rate_limit("u1", "/api/x")
    assert res.allowed is True

    # enabled, bypass
    svc = make_service(r, enabled=True)
    cfg = RateLimitConfig(default_rules=[], user_overrides={
        "u1": UserRateLimit(user_id="u1", bypass_rate_limit=True)
    })
    async def _cfg(): return cfg
    svc._get_config = _cfg  # type: ignore[assignment]
    res2 = await svc.check_rate_limit("u1", "/api/x", config=None, username="alice")
    assert res2.allowed is True

    # no matching rule -> allowed
    cfg2 = RateLimitConfig(default_rules=[])
    async def _cfg2(): return cfg2
    svc._get_config = _cfg2  # type: ignore[assignment]
    res3 = await svc.check_rate_limit("u2", "/none")
    assert res3.allowed is True


@pytest.mark.asyncio
async def test_sliding_window_allowed_and_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    r = FakeRedis(); r.count = 2; r.oldest = datetime.now(timezone.utc).timestamp() - 10
    svc = make_service(r)
    # matching rule with window 5, limit 3
    rule = RateLimitRule(endpoint_pattern=r"^/api/v1/x", group=EndpointGroup.API, requests=3, window_seconds=5,
                         algorithm=RateLimitAlgorithm.SLIDING_WINDOW)
    cfg = RateLimitConfig(default_rules=[rule])
    async def _cfg3(): return cfg
    svc._get_config = _cfg3  # type: ignore[assignment]
    ok = await svc.check_rate_limit("u", "/api/v1/x")
    assert ok.allowed is True and ok.remaining >= 0

    # Now exceed limit
    r.count = 5
    rej = await svc.check_rate_limit("u", "/api/v1/x")
    assert rej.allowed is False and rej.retry_after is not None

    # Provided config with global_enabled False
    cfg3 = RateLimitConfig(default_rules=[rule], global_enabled=False)
    res_disabled = await svc.check_rate_limit("u", "/api/v1/x", config=cfg3)
    assert res_disabled.allowed is True


@pytest.mark.asyncio
async def test_token_bucket_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    r = FakeRedis(); r.count = 0; now = datetime.now(timezone.utc).timestamp()
    # Preload bucket with 1.5 tokens so allowed, then later cause rejection
    bucket = {"tokens": 2.0, "last_refill": now}
    r.store["rl:tb:u:/api/v1/t"] = json.dumps(bucket)
    svc = make_service(r)
    rule = RateLimitRule(endpoint_pattern=r"^/api/v1/t", group=EndpointGroup.API, requests=2, window_seconds=10,
                         burst_multiplier=1.0, algorithm=RateLimitAlgorithm.TOKEN_BUCKET)
    cfg = RateLimitConfig(default_rules=[rule])
    async def _cfg(): return cfg
    svc._get_config = _cfg  # type: ignore[assignment]
    ok = await svc.check_rate_limit("u", "/api/v1/t")
    assert ok.allowed is True

    # Exhaust tokens -> rejected
    r.store["rl:tb:u:/api/v1/t"] = json.dumps({"tokens": 0.0, "last_refill": now})
    rej = await svc.check_rate_limit("u", "/api/v1/t")
    assert rej.allowed is False and rej.retry_after is not None

    # User multiplier applied; still allowed path
    cfg_mul = RateLimitConfig(default_rules=[RateLimitRule(endpoint_pattern=r"^/m", group=EndpointGroup.API, requests=2, window_seconds=10, algorithm=RateLimitAlgorithm.SLIDING_WINDOW)], user_overrides={"u": UserRateLimit(user_id="u", global_multiplier=2.0)})
    async def _cfg_mul(): return cfg_mul
    svc._get_config = _cfg_mul  # type: ignore[assignment]
    r.count = 0
    ok_mul = await svc.check_rate_limit("u", "/m")
    assert ok_mul.allowed is True


@pytest.mark.asyncio
async def test_config_update_and_user_helpers() -> None:
    r = FakeRedis(); r.count = 0
    svc = make_service(r)
    cfg = RateLimitConfig(default_rules=[RateLimitRule(endpoint_pattern=r"^/a", group=EndpointGroup.API, requests=1, window_seconds=1)])
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
async def test_ip_based_rate_limiting():
    """Test IP-based rate limiting."""
    r = FakeRedis()
    r.count = 1
    svc = make_service(r)
    
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
    async def _cfg():
        return cfg
    svc._get_config = _cfg  # type: ignore[assignment]
    
    # Check with IP identifier
    result = await svc.check_rate_limit("ip:192.168.1.1", "/api/test")
    assert result.allowed is True
    
    # Verify metrics were recorded for IP
    assert hasattr(svc.metrics, 'ip_checks')


@pytest.mark.asyncio
async def test_get_config_error_handling():
    """Test error handling when getting config fails."""
    r = FakeRedis()
    svc = make_service(r)
    
    # Mock redis.get to raise exception
    async def failing_get(key):
        raise ConnectionError("Redis connection failed")
    
    r.get = failing_get
    
    # Should raise the exception
    with pytest.raises(ConnectionError):
        await svc.check_rate_limit("user1", "/api/test")


@pytest.mark.asyncio
async def test_sliding_window_redis_error():
    """Test sliding window with Redis pipeline error."""
    r = FakeRedis()
    svc = make_service(r)
    
    # Mock pipeline to fail
    class FailingPipe:
        def zremrangebyscore(self, *a, **k):
            return self
        def zadd(self, *a, **k):
            return self
        def zcard(self, *a, **k):
            return self
        def expire(self, *a, **k):
            return self
        async def execute(self):
            raise ConnectionError("Pipeline failed")
    
    r.pipeline = lambda: FailingPipe()
    
    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW
    )
    cfg = RateLimitConfig(default_rules=[rule])
    
    # Should raise error
    with pytest.raises(ConnectionError):
        await svc._check_sliding_window(
            "user1", 
            "/api/test", 
            int(rule.requests),
            rule.window_seconds,
            rule
        )


@pytest.mark.asyncio
async def test_token_bucket_invalid_data():
    """Test token bucket with invalid JSON data."""
    r = FakeRedis()
    r.store["rl:tb:user:/api"] = "invalid-json"
    svc = make_service(r)
    
    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET
    )
    
    # Should raise JSONDecodeError for invalid JSON
    import json
    with pytest.raises(json.JSONDecodeError):
        await svc._check_token_bucket(
            "user", 
            "/api",
            int(rule.requests),
            rule.window_seconds,
            rule.burst_multiplier or 1.0,
            rule
        )


@pytest.mark.asyncio
async def test_update_config_serialization_error():
    """Test config update with serialization error."""
    r = FakeRedis()
    svc = make_service(r)
    
    # Mock setex to fail
    async def failing_setex(key, ttl, value):
        raise ValueError("Serialization failed")
    
    r.setex = failing_setex
    
    cfg = RateLimitConfig(default_rules=[])
    
    # Should raise error
    with pytest.raises(ValueError):
        await svc.update_config(cfg)


@pytest.mark.asyncio
async def test_get_user_rate_limit_not_found():
    """Test getting non-existent user rate limit."""
    r = FakeRedis()
    svc = make_service(r)
    
    result = await svc.get_user_rate_limit("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_reset_user_limits_error():
    """Test reset user limits with Redis error."""
    r = FakeRedis()
    svc = make_service(r)
    
    # Mock scan to fail
    async def failing_scan(cursor, match=None, count=100):
        raise ConnectionError("Scan failed")
    
    r.scan = failing_scan
    
    # Should raise error
    with pytest.raises(ConnectionError):
        await svc.reset_user_limits("user")


@pytest.mark.asyncio
async def test_get_usage_stats_with_errors():
    """Test get usage stats with various error conditions."""
    r = FakeRedis()
    svc = make_service(r)
    
    # Mock zrange to fail for some keys
    call_count = 0
    async def sometimes_failing_zrange(key, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("zrange failed")
        return [[b"timestamp", 1000.0]]
    
    r.zrange = sometimes_failing_zrange
    r.scans = [(0, [b"rl:sw:user:/api:key1"])]
    
    stats = await svc.get_usage_stats("user")
    assert isinstance(stats, dict)


@pytest.mark.asyncio
async def test_check_rate_limit_with_user_override():
    """Test rate limit check with user-specific overrides."""
    r = FakeRedis()
    r.count = 10  # High count to trigger limit
    svc = make_service(r)
    
    rule = RateLimitRule(
        endpoint_pattern=r"^/api",
        group=EndpointGroup.API,
        requests=5,
        window_seconds=60
    )
    
    # User with higher multiplier to allow more requests
    user_override = UserRateLimit(
        user_id="special_user",
        global_multiplier=4.0  # 4x the normal limit = 20 requests
    )
    
    cfg = RateLimitConfig(
        default_rules=[rule],
        user_overrides={"special_user": user_override}
    )
    
    async def _cfg():
        return cfg
    svc._get_config = _cfg  # type: ignore[assignment]
    
    # Normal user should be blocked
    result1 = await svc.check_rate_limit("normal_user", "/api/test")
    assert result1.allowed is False
    
    # Special user should be allowed (higher limit via multiplier)
    result2 = await svc.check_rate_limit("special_user", "/api/test")
    assert result2.allowed is True
