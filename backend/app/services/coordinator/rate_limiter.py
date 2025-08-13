import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.core.logging import logger
from app.core.metrics import Counter, Gauge


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_size: int = 10

    # Per-user limits (can be lower than global)
    user_requests_per_minute: int = 30
    user_requests_per_hour: int = 500
    user_requests_per_day: int = 5000


class TokenBucket:
    """Token bucket implementation for rate limiting"""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = float(capacity)
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from bucket"""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update

            # Refill tokens
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.refill_rate
            )
            self.last_update = now

            # Try to consume
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    async def get_wait_time(self, tokens: int = 1) -> float:
        """Get time to wait until tokens are available"""
        async with self._lock:
            if self.tokens >= tokens:
                return 0.0

            needed = tokens - self.tokens
            return needed / self.refill_rate


class RateLimiter:
    """Rate limiter for execution requests"""

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()

        # Global rate limiters
        self.minute_bucket = TokenBucket(
            self.config.requests_per_minute,
            self.config.requests_per_minute / 60.0
        )
        self.hour_bucket = TokenBucket(
            self.config.requests_per_hour,
            self.config.requests_per_hour / 3600.0
        )
        self.day_bucket = TokenBucket(
            self.config.requests_per_day,
            self.config.requests_per_day / 86400.0
        )

        # Per-user rate limiters
        self.user_minute_buckets: Dict[str, TokenBucket] = {}
        self.user_hour_buckets: Dict[str, TokenBucket] = {}
        self.user_day_buckets: Dict[str, TokenBucket] = {}

        # Cleanup tracking
        self.last_cleanup = time.time()
        self._cleanup_lock = asyncio.Lock()

        # Metrics
        self.rate_limited = Counter(
            "execution_rate_limited_total",
            "Total rate limited requests",
            ["limit_type", "user_id"]
        )
        self.rate_limit_wait_time = Gauge(
            "execution_rate_limit_wait_seconds",
            "Current wait time for rate limit",
            ["limit_type", "user_id"]
        )

    async def check_rate_limit(
            self,
            user_id: Optional[str] = None,
            tokens: int = 1
    ) -> Tuple[bool, Optional[float], Optional[str]]:
        """
        Check if request is within rate limits
        
        Returns:
            Tuple of (allowed, wait_time_seconds, limit_type)
        """
        # Check global limits first
        if not await self.minute_bucket.consume(tokens):
            wait_time = await self.minute_bucket.get_wait_time(tokens)
            self.rate_limited.labels(
                limit_type="global_minute",
                user_id=user_id or "anonymous"
            ).inc()
            self.rate_limit_wait_time.labels(
                limit_type="global_minute",
                user_id=user_id or "anonymous"
            ).set(wait_time)
            return False, wait_time, "global_minute"

        if not await self.hour_bucket.consume(tokens):
            wait_time = await self.hour_bucket.get_wait_time(tokens)
            self.rate_limited.labels(
                limit_type="global_hour",
                user_id=user_id or "anonymous"
            ).inc()
            self.rate_limit_wait_time.labels(
                limit_type="global_hour",
                user_id=user_id or "anonymous"
            ).set(wait_time)
            return False, wait_time, "global_hour"

        if not await self.day_bucket.consume(tokens):
            wait_time = await self.day_bucket.get_wait_time(tokens)
            self.rate_limited.labels(
                limit_type="global_day",
                user_id=user_id or "anonymous"
            ).inc()
            self.rate_limit_wait_time.labels(
                limit_type="global_day",
                user_id=user_id or "anonymous"
            ).set(wait_time)
            return False, wait_time, "global_day"

        # Check per-user limits if user_id provided
        if user_id:
            # Get or create user buckets
            user_minute = await self._get_user_bucket(
                user_id,
                self.user_minute_buckets,
                self.config.user_requests_per_minute,
                self.config.user_requests_per_minute / 60.0
            )

            user_hour = await self._get_user_bucket(
                user_id,
                self.user_hour_buckets,
                self.config.user_requests_per_hour,
                self.config.user_requests_per_hour / 3600.0
            )

            user_day = await self._get_user_bucket(
                user_id,
                self.user_day_buckets,
                self.config.user_requests_per_day,
                self.config.user_requests_per_day / 86400.0
            )

            # Check user limits
            if not await user_minute.consume(tokens):
                wait_time = await user_minute.get_wait_time(tokens)
                self.rate_limited.labels(
                    limit_type="user_minute",
                    user_id=user_id
                ).inc()
                self.rate_limit_wait_time.labels(
                    limit_type="user_minute",
                    user_id=user_id
                ).set(wait_time)
                return False, wait_time, "user_minute"

            if not await user_hour.consume(tokens):
                wait_time = await user_hour.get_wait_time(tokens)
                self.rate_limited.labels(
                    limit_type="user_hour",
                    user_id=user_id
                ).inc()
                self.rate_limit_wait_time.labels(
                    limit_type="user_hour",
                    user_id=user_id
                ).set(wait_time)
                return False, wait_time, "user_hour"

            if not await user_day.consume(tokens):
                wait_time = await user_day.get_wait_time(tokens)
                self.rate_limited.labels(
                    limit_type="user_day",
                    user_id=user_id
                ).inc()
                self.rate_limit_wait_time.labels(
                    limit_type="user_day",
                    user_id=user_id
                ).set(wait_time)
                return False, wait_time, "user_day"

        # Periodically cleanup old user buckets
        await self._maybe_cleanup()

        return True, None, None

    async def get_remaining_quota(
            self,
            user_id: Optional[str] = None
    ) -> Dict[str, Dict[str, float]]:
        """Get remaining quota information"""
        global_quota = {
            "minute": self.minute_bucket.tokens,
            "hour": self.hour_bucket.tokens,
            "day": self.day_bucket.tokens
        }

        result = {"global": global_quota}

        if user_id and user_id in self.user_minute_buckets:
            user_quota = {
                "minute": self.user_minute_buckets[user_id].tokens,
                "hour": self.user_hour_buckets.get(user_id, TokenBucket(0, 0)).tokens,
                "day": self.user_day_buckets.get(user_id, TokenBucket(0, 0)).tokens
            }
            result["user"] = user_quota

        return result

    async def reset_user_limits(self, user_id: str) -> None:
        """Reset rate limits for specific user"""
        async with self._cleanup_lock:
            if user_id in self.user_minute_buckets:
                del self.user_minute_buckets[user_id]
            if user_id in self.user_hour_buckets:
                del self.user_hour_buckets[user_id]
            if user_id in self.user_day_buckets:
                del self.user_day_buckets[user_id]

        logger.info(f"Reset rate limits for user {user_id}")

    async def _get_user_bucket(
            self,
            user_id: str,
            bucket_dict: Dict[str, TokenBucket],
            capacity: int,
            refill_rate: float
    ) -> TokenBucket:
        """Get or create user token bucket"""
        if user_id not in bucket_dict:
            bucket_dict[user_id] = TokenBucket(capacity, refill_rate)
        return bucket_dict[user_id]

    async def _maybe_cleanup(self) -> None:
        """Cleanup old user buckets periodically"""
        now = time.time()
        if now - self.last_cleanup < 3600:  # Cleanup every hour
            return

        async with self._cleanup_lock:
            # Only cleanup if enough time has passed (double-check with lock)
            if now - self.last_cleanup < 3600:
                return

            self.last_cleanup = now

            # Remove buckets that haven't been used recently
            # This is a simple implementation - could be improved
            # For now, just limit the number of user buckets
            max_users = 10000

            for bucket_dict in [
                self.user_minute_buckets,
                self.user_hour_buckets,
                self.user_day_buckets
            ]:
                if len(bucket_dict) > max_users:
                    # Remove oldest entries (simplified - could track last access)
                    to_remove = len(bucket_dict) - max_users
                    for key in list(bucket_dict.keys())[:to_remove]:
                        del bucket_dict[key]

            logger.info(
                f"Rate limiter cleanup: "
                f"{len(self.user_minute_buckets)} active users"
            )
