import json
import math
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Generator, Optional, cast

import redis.asyncio as redis

from app.core.metrics.rate_limit import RateLimitMetrics
from app.core.tracing.utils import add_span_attributes
from app.domain.rate_limit import (
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    RateLimitStatus,
    UserRateLimit,
    UserRateLimitSummary,
)
from app.infrastructure.mappers import RateLimitConfigMapper
from app.settings import Settings


class RateLimitService:
    def __init__(self, redis_client: redis.Redis, settings: Settings, metrics: "RateLimitMetrics"):
        self.redis = redis_client
        self.settings = settings
        self.prefix = settings.RATE_LIMIT_REDIS_PREFIX
        self.metrics = metrics

        # Patterns to match IDs and replace with *
        self._uuid_pattern = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
        self._id_pattern = re.compile(r"/[0-9a-zA-Z]{20,}(?=/|$)")

    def _index_key(self, user_id: str) -> str:
        """Key of the Redis set that indexes all per-user rate limit state keys."""
        return f"{self.prefix}index:{user_id}"

    async def _register_user_key(self, user_id: str, key: str) -> None:
        """Index a runtime key under a user's set for fast CRUD without SCAN."""
        _ = await cast(Awaitable[int], self.redis.sadd(self._index_key(user_id), key))

    def _normalize_endpoint(self, endpoint: str) -> str:
        normalized = self._uuid_pattern.sub("*", endpoint)
        normalized = self._id_pattern.sub("/*", normalized)
        return normalized

    @contextmanager
    def _timer(self, histogram: Any, attrs: dict[str, str]) -> Generator[None, None, None]:
        start = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start) * 1000
            histogram.record(duration_ms, attrs)

    @dataclass
    class _Context:
        user_id: str
        endpoint: str
        normalized_endpoint: str
        authenticated: bool
        config: Optional[RateLimitConfig] = None
        rule: Optional[RateLimitRule] = None
        multiplier: float = 1.0
        effective_limit: int = 0
        algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW

    def _labels(self, ctx: "RateLimitService._Context") -> dict[str, str]:
        labels = {
            "authenticated": str(ctx.authenticated).lower(),
            "endpoint": ctx.normalized_endpoint,
            "algorithm": ctx.algorithm.value,
        }
        if ctx.rule is not None:
            labels.update(
                {"group": ctx.rule.group.value, "priority": str(ctx.rule.priority), "multiplier": str(ctx.multiplier)}
            )
        return labels

    def _unlimited(self, algo: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW) -> RateLimitStatus:
        return RateLimitStatus(
            allowed=True,
            limit=999999,
            remaining=999999,
            reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
            retry_after=None,
            matched_rule=None,
            algorithm=algo,
        )

    def _prepare_config(self, config: RateLimitConfig) -> None:
        # Precompile and sort rules for faster matching
        for rule in config.default_rules:
            if rule.compiled_pattern is None:
                rule.compiled_pattern = re.compile(rule.endpoint_pattern)
        config.default_rules.sort(key=lambda r: r.priority, reverse=True)
        for user_limit in config.user_overrides.values():
            for rule in user_limit.rules:
                if rule.compiled_pattern is None:
                    rule.compiled_pattern = re.compile(rule.endpoint_pattern)
            user_limit.rules.sort(key=lambda r: r.priority, reverse=True)

    async def check_rate_limit(
        self, user_id: str, endpoint: str, config: Optional[RateLimitConfig] = None
    ) -> RateLimitStatus:
        start_time = time.time()
        # Tracing attributes added at end of check
        ctx = RateLimitService._Context(
            user_id=user_id,
            endpoint=endpoint,
            normalized_endpoint=self._normalize_endpoint(endpoint),
            authenticated=not user_id.startswith("ip:"),
        )

        try:
            if not self.settings.RATE_LIMIT_ENABLED:
                # Track request when rate limiting is disabled
                self.metrics.requests_total.add(
                    1,
                    {
                        "authenticated": str(ctx.authenticated).lower(),
                        "endpoint": ctx.normalized_endpoint,
                        "algorithm": "disabled",
                    },
                )
                return self._unlimited()

            if config is None:
                with self._timer(self.metrics.redis_duration, {"operation": "get_config"}):
                    config = await self._get_config()
            ctx.config = config
            # Prepare config (compile/sort)
            self._prepare_config(config)

            if not config.global_enabled:
                return self._unlimited()

            # Check user overrides
            user_config = config.user_overrides.get(str(user_id))
            if user_config and user_config.bypass_rate_limit:
                self.metrics.bypass.add(1, {"endpoint": ctx.normalized_endpoint})
                self.metrics.requests_total.add(
                    1,
                    {
                        "authenticated": str(ctx.authenticated).lower(),
                        "endpoint": ctx.normalized_endpoint,
                        "algorithm": "bypassed",
                    },
                )
                return self._unlimited()

            # Find matching rule
            rule = self._find_matching_rule(endpoint, user_config, config)
            if not rule:
                self.metrics.requests_total.add(
                    1,
                    {
                        "authenticated": str(ctx.authenticated).lower(),
                        "endpoint": ctx.normalized_endpoint,
                        "algorithm": "no_limit",
                    },
                )
                return self._unlimited()

            # Apply user multiplier if exists
            ctx.rule = rule
            ctx.multiplier = user_config.global_multiplier if user_config else 1.0
            ctx.effective_limit = int(rule.requests * ctx.multiplier)
            ctx.algorithm = rule.algorithm

            # Track total requests with algorithm
            self.metrics.requests_total.add(
                1,
                {
                    "authenticated": str(ctx.authenticated).lower(),
                    "endpoint": ctx.normalized_endpoint,
                    "algorithm": rule.algorithm.value,
                },
            )

            # Record window size
            self.metrics.window_size.record(
                rule.window_seconds, {"endpoint": ctx.normalized_endpoint, "algorithm": rule.algorithm.value}
            )

            # Check rate limit based on algorithm (avoid duplicate branches)
            timer_attrs = {
                "algorithm": rule.algorithm.value,
                "endpoint": ctx.normalized_endpoint,
                "authenticated": str(ctx.authenticated).lower(),
            }
            with self._timer(self.metrics.algorithm_duration, timer_attrs):
                if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                    status = await self._check_token_bucket(
                        user_id, endpoint, ctx.effective_limit, rule.window_seconds, rule.burst_multiplier, rule
                    )
                else:
                    status = await self._check_sliding_window(
                        user_id, endpoint, ctx.effective_limit, rule.window_seconds, rule
                    )

            labels = self._labels(ctx)
            if status.allowed:
                self.metrics.allowed.add(1, labels)
            else:
                self.metrics.rejected.add(1, labels)

            self.metrics.remaining.record(status.remaining, labels)
            if status.limit > 0:
                quota_used = ((status.limit - status.remaining) / status.limit) * 100
                self.metrics.quota_usage.record(quota_used, labels)

            add_span_attributes(
                **{
                    "rate_limit.allowed": status.allowed,
                    "rate_limit.limit": status.limit,
                    "rate_limit.remaining": status.remaining,
                    "rate_limit.algorithm": status.algorithm.value,
                }
            )
            return status
        finally:
            self.metrics.check_duration.record(
                (time.time() - start_time) * 1000,
                {"endpoint": ctx.normalized_endpoint, "authenticated": str(ctx.authenticated).lower()},
            )

    async def _check_sliding_window(
        self, user_id: str, endpoint: str, limit: int, window_seconds: int, rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}sw:{user_id}:{endpoint}"
        await self._register_user_key(user_id, key)
        now = time.time()
        window_start = now - window_seconds

        normalized_endpoint = self._normalize_endpoint(endpoint)

        with self._timer(self.metrics.redis_duration, {"operation": "sliding_window", "endpoint": normalized_endpoint}):
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds * 2)
            results = await pipe.execute()

        count = results[2]
        remaining = max(0, limit - count)

        if count > limit:
            # Calculate retry after
            with self._timer(self.metrics.redis_duration, {"operation": "get_oldest_timestamp"}):
                oldest_timestamp = await self.redis.zrange(key, 0, 0, withscores=True)

            if oldest_timestamp:
                retry_after = int(oldest_timestamp[0][1] + window_seconds - now) + 1
            else:
                retry_after = window_seconds

            return RateLimitStatus(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=datetime.fromtimestamp(now + retry_after, timezone.utc),
                retry_after=retry_after,
                matched_rule=rule.endpoint_pattern,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            )

        return RateLimitStatus(
            allowed=True,
            limit=limit,
            remaining=remaining,
            reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
            retry_after=None,
            matched_rule=rule.endpoint_pattern,
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        )

    async def _check_token_bucket(
        self, user_id: str, endpoint: str, limit: int, window_seconds: int, burst_multiplier: float, rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}tb:{user_id}:{endpoint}"
        max_tokens = int(limit * burst_multiplier)
        refill_rate = limit / window_seconds

        normalized_endpoint = self._normalize_endpoint(endpoint)

        now = time.time()

        await self._register_user_key(user_id, key)

        # Get current bucket state
        with self._timer(
            self.metrics.redis_duration, {"operation": "token_bucket_get", "endpoint": normalized_endpoint}
        ):
            bucket_data = await self.redis.get(key)

        if bucket_data:
            bucket = json.loads(bucket_data)
            tokens = bucket["tokens"]
            last_refill = bucket["last_refill"]

            # Refill tokens
            time_passed = now - last_refill
            tokens_to_add = time_passed * refill_rate
            tokens = min(max_tokens, tokens + tokens_to_add)
        else:
            tokens = max_tokens
            last_refill = now

        # Record token bucket metrics
        self.metrics.token_bucket_tokens.record(
            tokens,
            {
                "endpoint": normalized_endpoint,
            },
        )
        self.metrics.token_bucket_refill_rate.record(refill_rate, {"endpoint": normalized_endpoint})

        # Try to consume a token
        if tokens >= 1:
            tokens -= 1
            bucket = {"tokens": tokens, "last_refill": now}

            with self._timer(
                self.metrics.redis_duration, {"operation": "token_bucket_set", "endpoint": normalized_endpoint}
            ):
                await self.redis.setex(key, window_seconds * 2, json.dumps(bucket))

            return RateLimitStatus(
                allowed=True,
                limit=limit,
                remaining=int(tokens),
                reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
                retry_after=None,
                matched_rule=rule.endpoint_pattern,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            )
        else:
            # Calculate when next token will be available
            retry_after = int((1 - tokens) / refill_rate) + 1

            return RateLimitStatus(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=datetime.fromtimestamp(now + retry_after, timezone.utc),
                retry_after=retry_after,
                matched_rule=rule.endpoint_pattern,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            )

    def _find_matching_rule(
        self, endpoint: str, user_config: Optional[UserRateLimit], global_config: RateLimitConfig
    ) -> Optional[RateLimitRule]:
        rules = []

        # Add user-specific rules (already pre-sorted)
        if user_config and user_config.rules:
            rules.extend(user_config.rules)

        # Add global default rules (already pre-sorted)
        rules.extend(global_config.default_rules)

        # Find first match using precompiled patterns
        for rule in rules:
            if not rule.enabled:
                continue
            pat = rule.compiled_pattern or re.compile(rule.endpoint_pattern)
            rule.compiled_pattern = pat
            if pat.match(endpoint):
                return rule

        return None

    async def _get_config(self) -> RateLimitConfig:
        # Try to get from Redis cache
        config_key = f"{self.prefix}config"
        config_data = await self.redis.get(config_key)
        mapper = RateLimitConfigMapper()

        if config_data:
            config = mapper.model_validate_json(config_data)
        else:
            # Return default config and cache it
            config = RateLimitConfig.get_default_config()
            await self.redis.setex(
                config_key,
                300,  # Cache for 5 minutes
                mapper.model_dump_json(config),
            )

        # Prepare for fast matching
        self._prepare_config(config)

        # Always record current config metrics when loading
        active_rules_count = len([r for r in config.default_rules if r.enabled])
        custom_users_count = len(config.user_overrides)
        bypass_users_count = len([u for u in config.user_overrides.values() if u.bypass_rate_limit])

        self.metrics.active_rules.record(active_rules_count)
        self.metrics.custom_users.record(custom_users_count)
        self.metrics.bypass_users.record(bypass_users_count)

        return config

    async def update_config(self, config: RateLimitConfig) -> None:
        config_key = f"{self.prefix}config"
        mapper = RateLimitConfigMapper()

        with self._timer(self.metrics.redis_duration, {"operation": "update_config"}):
            await self.redis.setex(config_key, 300, mapper.model_dump_json(config))

        # Update configuration metrics - just record the absolute values
        active_rules_count = len([r for r in config.default_rules if r.enabled])
        custom_users_count = len(config.user_overrides)
        bypass_users_count = len([u for u in config.user_overrides.values() if u.bypass_rate_limit])

        # Record current values (histograms will track the distribution)
        self.metrics.active_rules.record(active_rules_count)
        self.metrics.custom_users.record(custom_users_count)
        self.metrics.bypass_users.record(bypass_users_count)

    async def update_user_rate_limit(self, user_id: str, user_limit: UserRateLimit) -> None:
        config = await self._get_config()
        config.user_overrides[str(user_id)] = user_limit
        await self.update_config(config)

    async def get_user_rate_limit(self, user_id: str) -> Optional[UserRateLimit]:
        config = await self._get_config()
        return config.user_overrides.get(str(user_id))

    async def get_user_rate_limit_summary(
        self,
        user_id: str,
        config: Optional[RateLimitConfig] = None,
    ) -> UserRateLimitSummary:
        """Return a summary for the user's rate limit configuration with sensible defaults.

        - has_custom_limits is true only if an override exists and differs from defaults
        - bypass_rate_limit/global_multiplier reflect override or defaults (False/1.0)
        """
        if config is None:
            config = await self._get_config()
        override = config.user_overrides.get(str(user_id))
        if override:
            rules_count = len(override.rules)
            has_custom = (
                override.bypass_rate_limit
                or not math.isclose(override.global_multiplier, 1.0, rel_tol=1e-9, abs_tol=1e-12)
                or rules_count > 0
            )
            return UserRateLimitSummary(
                user_id=str(user_id),
                has_custom_limits=has_custom,
                bypass_rate_limit=override.bypass_rate_limit,
                global_multiplier=override.global_multiplier,
                rules_count=rules_count,
            )
        # Defaults when no override exists
        return UserRateLimitSummary(
            user_id=str(user_id),
            has_custom_limits=False,
            bypass_rate_limit=False,
            global_multiplier=1.0,
            rules_count=0,
        )

    async def get_user_rate_limit_summaries(self, user_ids: list[str]) -> dict[str, UserRateLimitSummary]:
        """Batch build summaries for a set of users using a single config load."""
        config = await self._get_config()
        summaries: dict[str, UserRateLimitSummary] = {}
        for uid in user_ids:
            summaries[uid] = await self.get_user_rate_limit_summary(uid, config=config)
        return summaries

    async def reset_user_limits(self, user_id: str) -> None:
        index_key = self._index_key(user_id)
        keys = await cast(Awaitable[set[Any]], self.redis.smembers(index_key))
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(index_key)

    async def get_usage_stats(self, user_id: str) -> dict:
        stats: dict[str, dict[str, object]] = {}
        index_key = self._index_key(user_id)
        keys = await cast(Awaitable[set[Any]], self.redis.smembers(index_key))
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(":")
            # Expect: <prefix>(sw|tb):<user_id>:<endpoint>
            if len(parts) < 4:
                continue
            algo = parts[1]
            endpoint = ":".join(parts[3:])
            if algo == "sw":
                count = await cast(Awaitable[int], self.redis.zcard(key))
                stats[endpoint] = {"count": count, "algorithm": "sliding_window"}
            elif algo == "tb":
                bucket_data = await self.redis.get(key)
                if bucket_data:
                    bucket = json.loads(bucket_data)
                    stats[endpoint] = {
                        "tokens_remaining": bucket.get("tokens", 0),
                        "algorithm": "token_bucket",
                    }
        return stats
