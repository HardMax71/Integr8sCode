import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.utils import StringEnum


class RateLimitAlgorithm(StringEnum):
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"
    LEAKY_BUCKET = "leaky_bucket"


class EndpointGroup(StringEnum):
    EXECUTION = "execution"
    ADMIN = "admin"
    SSE = "sse"
    WEBSOCKET = "websocket"
    AUTH = "auth"
    PUBLIC = "public"
    API = "api"


@dataclass
class RateLimitRule:
    endpoint_pattern: str
    group: EndpointGroup
    requests: int
    window_seconds: int
    burst_multiplier: float = 1.5
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    priority: int = 0
    enabled: bool = True
    # Internal cache for matching speed; not serialized
    compiled_pattern: Optional[re.Pattern[str]] = field(default=None, repr=False, compare=False)


@dataclass
class UserRateLimit:
    user_id: str
    rules: List[RateLimitRule] = field(default_factory=list)
    global_multiplier: float = 1.0
    bypass_rate_limit: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None


@dataclass
class RateLimitConfig:
    default_rules: List[RateLimitRule] = field(default_factory=list)
    user_overrides: Dict[str, UserRateLimit] = field(default_factory=dict)
    global_enabled: bool = True
    redis_ttl: int = 3600

    @classmethod
    def get_default_config(cls) -> "RateLimitConfig":
        return cls(
            default_rules=[
                RateLimitRule(
                    endpoint_pattern=r"^/api/v1/execute",
                    group=EndpointGroup.EXECUTION,
                    requests=10,
                    window_seconds=60,
                    burst_multiplier=1.5,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                    priority=10,
                    enabled=True,
                ),
                RateLimitRule(
                    endpoint_pattern=r"^/api/v1/admin/.*",
                    group=EndpointGroup.ADMIN,
                    requests=100,
                    window_seconds=60,
                    burst_multiplier=2.0,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                    priority=5,
                    enabled=True,
                ),
                RateLimitRule(
                    endpoint_pattern=r"^/api/v1/events/.*",
                    group=EndpointGroup.SSE,
                    requests=5,
                    window_seconds=60,
                    burst_multiplier=1.0,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                    priority=3,
                    enabled=True,
                ),
                RateLimitRule(
                    endpoint_pattern=r"^/api/v1/ws",
                    group=EndpointGroup.WEBSOCKET,
                    requests=5,
                    window_seconds=60,
                    burst_multiplier=1.0,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                    priority=3,
                    enabled=True,
                ),
                RateLimitRule(
                    endpoint_pattern=r"^/api/v1/auth/.*",
                    group=EndpointGroup.AUTH,
                    requests=20,
                    window_seconds=60,
                    burst_multiplier=1.5,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                    priority=7,
                    enabled=True,
                ),
                RateLimitRule(
                    endpoint_pattern=r"^/api/v1/.*",
                    group=EndpointGroup.API,
                    requests=60,
                    window_seconds=60,
                    burst_multiplier=1.5,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
                    priority=1,
                    enabled=True,
                ),
            ],
            global_enabled=True,
            redis_ttl=3600,
        )


@dataclass
class RateLimitStatus:
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime
    retry_after: Optional[int] = None
    matched_rule: Optional[str] = None
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW


@dataclass
class UserRateLimitSummary:
    """Summary view for a user's rate limit configuration.

    Always present for callers; reflects defaults when no override exists.
    """

    user_id: str
    has_custom_limits: bool
    bypass_rate_limit: bool
    global_multiplier: float
    rules_count: int
