from datetime import datetime, timedelta, timezone

import pytest
from app.domain.rate_limit.rate_limit_models import (
    EndpointGroup,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    UserRateLimit,
)
from app.infrastructure.mappers import (
    RateLimitConfigMapper,
    RateLimitRuleMapper,
    UserRateLimitMapper,
)

pytestmark = pytest.mark.unit


def test_rule_mapper_roundtrip_defaults() -> None:
    rule = RateLimitRule(endpoint_pattern=r"^/api", group=EndpointGroup.API, requests=10, window_seconds=60)
    d = RateLimitRuleMapper.to_dict(rule)
    r2 = RateLimitRuleMapper.from_dict(d)
    assert r2.endpoint_pattern == rule.endpoint_pattern and r2.algorithm == RateLimitAlgorithm.SLIDING_WINDOW


def test_user_rate_limit_mapper_roundtrip_and_dates() -> None:
    now = datetime.now(timezone.utc)
    u = UserRateLimit(user_id="u1", rules=[
        RateLimitRule(endpoint_pattern="/x", group=EndpointGroup.API, requests=1, window_seconds=1)], notes="n")
    d = UserRateLimitMapper.to_dict(u)
    u2 = UserRateLimitMapper.from_dict(d)
    assert u2.user_id == "u1" and len(u2.rules) == 1 and isinstance(u2.created_at, datetime)

    # from string timestamps
    d["created_at"] = now.isoformat()
    d["updated_at"] = (now + timedelta(seconds=1)).isoformat()
    u3 = UserRateLimitMapper.from_dict(d)
    assert u3.created_at <= u3.updated_at


def test_config_mapper_roundtrip_and_json() -> None:
    cfg = RateLimitConfig(
        default_rules=[RateLimitRule(endpoint_pattern="/a", group=EndpointGroup.API, requests=1, window_seconds=1)],
        user_overrides={"u": UserRateLimit(user_id="u")}, global_enabled=False, redis_ttl=10)
    d = RateLimitConfigMapper.to_dict(cfg)
    c2 = RateLimitConfigMapper.from_dict(d)
    assert c2.redis_ttl == 10 and len(c2.default_rules) == 1 and "u" in c2.user_overrides

    js = RateLimitConfigMapper.model_dump_json(cfg)
    c3 = RateLimitConfigMapper.model_validate_json(js)
    assert isinstance(c3, RateLimitConfig) and c3.global_enabled is False
