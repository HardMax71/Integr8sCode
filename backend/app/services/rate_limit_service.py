from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as redis
from pydantic import TypeAdapter

from app.core.metrics import RateLimitMetrics
from app.domain.rate_limit import (
    EndpointUsageStats,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    RateLimitStatus,
    UserRateLimit,
    UserRateLimitSummary,
)
from app.settings import Settings

_config_adapter = TypeAdapter(RateLimitConfig)


class RateLimitService:
    def __init__(self, redis_client: redis.Redis, settings: Settings, metrics: RateLimitMetrics):
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
        await self.redis.sadd(self._index_key(user_id), key)  # type: ignore[misc]

    def _normalize_endpoint(self, endpoint: str) -> str:
        normalized = self._uuid_pattern.sub("*", endpoint)
        normalized = self._id_pattern.sub("/*", normalized)
        return normalized

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
        normalized_endpoint = self._normalize_endpoint(endpoint)
        authenticated = not user_id.startswith("ip:")

        if config is None:
            config = await self._get_config()
        self._prepare_config(config)

        if not config.global_enabled:
            return self._unlimited()

        user_config = config.user_overrides.get(str(user_id))
        if user_config and user_config.bypass_rate_limit:
            self.metrics.record_bypass(normalized_endpoint)
            self.metrics.record_request(normalized_endpoint, authenticated, "bypassed")
            return self._unlimited()

        rule = self._find_matching_rule(endpoint, user_config, config)
        if not rule:
            self.metrics.record_request(normalized_endpoint, authenticated, "no_limit")
            return self._unlimited()

        multiplier = user_config.global_multiplier if user_config else 1.0
        effective_limit = int(rule.requests * multiplier)

        self.metrics.record_request(normalized_endpoint, authenticated, rule.algorithm)

        if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            status = await self._check_token_bucket(
                user_id, endpoint, effective_limit, rule.window_seconds, rule.burst_multiplier, rule
            )
        else:
            status = await self._check_sliding_window(
                user_id, endpoint, effective_limit, rule.window_seconds, rule
            )

        if status.allowed:
            self.metrics.record_allowed(normalized_endpoint, rule.group)
        else:
            self.metrics.record_rejected(normalized_endpoint, rule.group)

        return status

    async def _check_sliding_window(
        self, user_id: str, endpoint: str, limit: int, window_seconds: int, rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}sw:{user_id}:{endpoint}"
        await self._register_user_key(user_id, key)
        now = time.time()
        window_start = now - window_seconds

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds * 2)
        results = await pipe.execute()

        count = results[2]
        remaining = max(0, limit - count)

        if count > limit:
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
        now = time.time()

        await self._register_user_key(user_id, key)

        bucket_data = await self.redis.get(key)
        if bucket_data:
            bucket = json.loads(bucket_data)
            tokens = bucket["tokens"]
            last_refill = bucket["last_refill"]
            time_passed = now - last_refill
            tokens_to_add = time_passed * refill_rate
            tokens = min(max_tokens, tokens + tokens_to_add)
        else:
            tokens = max_tokens

        if tokens >= 1:
            tokens -= 1
            await self.redis.setex(key, window_seconds * 2, json.dumps({"tokens": tokens, "last_refill": now}))

            return RateLimitStatus(
                allowed=True,
                limit=limit,
                remaining=int(tokens),
                reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
                retry_after=None,
                matched_rule=rule.endpoint_pattern,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            )

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
        config_key = f"{self.prefix}config"
        config_data = await self.redis.get(config_key)

        if config_data:
            config = _config_adapter.validate_json(config_data)
        else:
            config = RateLimitConfig.get_default_config()
            await self.redis.setex(config_key, 300, _config_adapter.dump_json(config))

        self._prepare_config(config)
        return config

    async def update_config(self, config: RateLimitConfig) -> None:
        config_key = f"{self.prefix}config"
        await self.redis.setex(config_key, 300, _config_adapter.dump_json(config))

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
        keys = await self.redis.smembers(index_key)  # type: ignore[misc]
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(index_key)

    async def get_usage_stats(self, user_id: str) -> dict[str, EndpointUsageStats]:
        stats: dict[str, EndpointUsageStats] = {}
        index_key = self._index_key(user_id)
        keys = await self.redis.smembers(index_key)  # type: ignore[misc]
        if not keys:
            return stats

        config = await self._get_config()
        user_config = config.user_overrides.get(str(user_id))
        multiplier = user_config.global_multiplier if user_config else 1.0

        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(":")
            # Expect: <prefix>(sw|tb):<user_id>:<endpoint>
            if len(parts) < 4:
                continue
            algo = parts[1]
            endpoint = ":".join(parts[3:])

            if algo == "sw":
                count = await self.redis.zcard(key)
                rule = self._find_matching_rule(endpoint, user_config, config)
                limit = int(rule.requests * multiplier) if rule else 0
                remaining = max(0, limit - count)
                stats[endpoint] = EndpointUsageStats(
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW, remaining=remaining
                )
            elif algo == "tb":
                bucket_data = await self.redis.get(key)
                if bucket_data:
                    bucket = json.loads(bucket_data)
                    stats[endpoint] = EndpointUsageStats(
                        algorithm=RateLimitAlgorithm.TOKEN_BUCKET, remaining=int(bucket.get("tokens", 0))
                    )
        return stats
