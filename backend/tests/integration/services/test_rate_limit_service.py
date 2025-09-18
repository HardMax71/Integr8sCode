import asyncio
import pytest

from app.domain.rate_limit import EndpointGroup, RateLimitAlgorithm, RateLimitConfig, RateLimitRule, UserRateLimit
from app.services.rate_limit_service import RateLimitService


pytestmark = [pytest.mark.integration, pytest.mark.redis]


@pytest.mark.asyncio
async def test_rate_limit_happy_path_and_block(scope) -> None:  # type: ignore[valid-type]
    svc: RateLimitService = await scope.get(RateLimitService)

    # Ensure rate limiting enabled for this test
    svc.settings.RATE_LIMIT_ENABLED = True

    # Install a small custom rule for a test user on a synthetic endpoint
    user_id = "user-test"
    endpoint = "/api/v1/limits/demo"

    cfg = RateLimitConfig.get_default_config()
    rule = RateLimitRule(
        endpoint_pattern=r"^/api/v1/limits/demo$",
        group=EndpointGroup.API,
        requests=2,
        window_seconds=2,
        burst_multiplier=1.0,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        priority=50,
        enabled=True,
    )
    cfg.user_overrides[user_id] = UserRateLimit(user_id=user_id, rules=[rule])
    await svc.update_config(cfg)

    # First two requests allowed, third blocked
    s1 = await svc.check_rate_limit(user_id, endpoint)
    s2 = await svc.check_rate_limit(user_id, endpoint)
    s3 = await svc.check_rate_limit(user_id, endpoint)

    assert s1.allowed is True and s2.allowed is True
    assert s3.allowed is False and s3.retry_after is not None and s3.retry_after > 0

    # Reset user keys and ensure usage stats clears
    stats_before = await svc.get_usage_stats(user_id)
    assert endpoint in stats_before or any("/api/v1/limits/demo" in k for k in stats_before)

    await svc.reset_user_limits(user_id)
    stats_after = await svc.get_usage_stats(user_id)
    assert stats_after == {}

