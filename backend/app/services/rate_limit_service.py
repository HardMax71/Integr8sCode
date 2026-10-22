from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import redis.asyncio as redis
import structlog
from opentelemetry import trace
from opentelemetry.util.types import AttributeValue
from pydantic import Json, TypeAdapter

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
_user_limit_adapter = TypeAdapter(UserRateLimit)
_overrides_adapter = TypeAdapter(dict[str, Json[UserRateLimit]])
_keys_adapter = TypeAdapter(set[str])


class RateLimitService:
    def __init__(
        self,
        redis_client: redis.Redis,
        settings: Settings,
        tracer: trace.Tracer,
        logger: structlog.stdlib.BoundLogger,
    ):
        self.redis = redis_client
        self.settings = settings
        self.logger = logger
        self.prefix = settings.RATE_LIMIT_REDIS_PREFIX
        self._tracer = tracer
        self._pattern_cache: dict[str, re.Pattern[str]] = {}

        # Patterns to match IDs and replace with *
        self._uuid_pattern = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
        self._id_pattern = re.compile(r"/[0-9a-zA-Z]{20,}(?=/|$)")

    def _report_request(self, endpoint: str, authenticated: bool, algorithm: str) -> None:
        attributes: dict[str, AttributeValue] = {
            "rate_limit.endpoint": endpoint,
            "rate_limit.authenticated": authenticated,
            "rate_limit.algorithm": algorithm,
        }
        self._tracer.start_span("rate_limit.request", attributes=attributes).end()

    def _index_key(self, user_id: str) -> str:
        """Key of the Redis set that indexes all per-user rate limit state keys."""
        return f"{self.prefix}index:{user_id}"

    async def _register_user_key(self, user_id: str, key: str) -> None:
        """Index a runtime key under a user's set for fast CRUD without SCAN."""
        await self.redis.sadd(self._index_key(user_id), key)

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
            algorithm=algo,
        )

    def _compile_pattern(self, endpoint_pattern: str) -> re.Pattern[str]:
        pat = self._pattern_cache.get(endpoint_pattern)
        if pat is None:
            pat = re.compile(endpoint_pattern)
            self._pattern_cache[endpoint_pattern] = pat
        return pat

    def _prepare_config(self, config: RateLimitConfig) -> None:
        config.default_rules.sort(key=lambda r: r.priority, reverse=True)
        for user_limit in config.user_overrides.values():
            user_limit.rules.sort(key=lambda r: r.priority, reverse=True)

    async def check_rate_limit(self, user_id: str, endpoint: str) -> RateLimitStatus:
        """Check a request against its limit, letting it through when Redis fails."""
        try:
            return await self._check(user_id, endpoint, await self._get_config())
        except redis.RedisError as e:
            self.logger.error("Rate limit check failed, allowing the request", endpoint=endpoint, error=str(e))
            self._report_request(self._normalize_endpoint(endpoint), not user_id.startswith("ip:"), "redis_error")
            return self._unlimited()

    async def _check(self, user_id: str, endpoint: str, config: RateLimitConfig) -> RateLimitStatus:
        normalized_endpoint = self._normalize_endpoint(endpoint)
        authenticated = not user_id.startswith("ip:")

        if not config.global_enabled:
            return self._unlimited()

        user_config = self._user_limit(config, user_id)
        if user_config.bypass_rate_limit:
            self._report_request(normalized_endpoint, authenticated, "bypassed")
            return self._unlimited()

        for rule in self._matching_rules(endpoint, user_config, config):
            return await self._apply_rule(user_id, endpoint, rule, user_config.global_multiplier)

        self._report_request(normalized_endpoint, authenticated, "no_limit")
        return self._unlimited()

    async def _apply_rule(self, user_id: str, endpoint: str, rule: RateLimitRule, multiplier: float) -> RateLimitStatus:
        normalized_endpoint = self._normalize_endpoint(endpoint)
        effective_limit = int(rule.requests * multiplier)

        self._report_request(normalized_endpoint, not user_id.startswith("ip:"), rule.algorithm)

        if rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            status = await self._check_token_bucket(
                user_id, endpoint, effective_limit, rule.window_seconds, rule.burst_multiplier, rule
            )
        else:
            status = await self._check_sliding_window(user_id, endpoint, effective_limit, rule.window_seconds, rule)

        attributes: dict[str, AttributeValue] = {
            "rate_limit.endpoint": normalized_endpoint,
            "rate_limit.group": rule.group,
            "rate_limit.allowed": status.allowed,
        }
        self._tracer.start_span("rate_limit.decision", attributes=attributes).end()

        return status

    async def _check_sliding_window(
        self, user_id: str, endpoint: str, limit: int, window_seconds: int, rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}sw:{user_id}:{endpoint}"
        await self._register_user_key(user_id, key)
        now = time.time()
        window_start = now - window_seconds

        # --8<-- [start:check_sliding_window]
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {f"{now}:{uuid4().hex}": now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds * 2)
        results = await pipe.execute()
        # --8<-- [end:check_sliding_window]

        count = results[2]
        remaining = max(0, limit - count)

        if count > limit:
            oldest_timestamp = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest_timestamp:
                retry_after = int(float(oldest_timestamp[0][1]) + window_seconds - now) + 1
            else:
                retry_after = window_seconds

            return RateLimitStatus(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_at=datetime.fromtimestamp(now + retry_after, timezone.utc),
                retry_after=retry_after,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            )

        return RateLimitStatus(
            allowed=True,
            limit=limit,
            remaining=remaining,
            reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        )

    _TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local tokens = max_tokens
local last_refill = now

local bucket_data = redis.call('GET', key)
if bucket_data then
    local ok, bucket = pcall(cjson.decode, bucket_data)
    if ok and bucket['tokens'] and bucket['last_refill'] then
        tokens = bucket['tokens']
        last_refill = bucket['last_refill']
        local time_passed = now - last_refill
        tokens = math.min(max_tokens, tokens + time_passed * refill_rate)
    end
end

local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end

redis.call('SETEX', key, ttl, cjson.encode({tokens=tokens, last_refill=now}))
return {allowed, tostring(tokens)}
"""

    async def _check_token_bucket(
        self, user_id: str, endpoint: str, limit: int, window_seconds: int, burst_multiplier: float, rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}tb:{user_id}:{endpoint}"
        max_tokens = int(limit * burst_multiplier)
        refill_rate = limit / window_seconds
        now = time.time()

        await self._register_user_key(user_id, key)

        # --8<-- [start:check_token_bucket]
        result = await self.redis.eval(
            self._TOKEN_BUCKET_LUA,
            1,
            key,
            max_tokens,
            refill_rate,
            now,
            window_seconds * 2,
        )
        allowed = bool(result[0])
        tokens = float(result[1])
        # --8<-- [end:check_token_bucket]

        if allowed:
            return RateLimitStatus(
                allowed=True,
                limit=limit,
                remaining=int(tokens),
                reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            )

        retry_after = int((1 - tokens) / refill_rate) + 1
        return RateLimitStatus(
            allowed=False,
            limit=limit,
            remaining=0,
            reset_at=datetime.fromtimestamp(now + retry_after, timezone.utc),
            retry_after=retry_after,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )

    @staticmethod
    def _user_limit(config: RateLimitConfig, user_id: str) -> UserRateLimit:
        """The user's override, or the neutral defaults when there is none."""
        return config.user_overrides.get(user_id, UserRateLimit(user_id=user_id))

    def _matching_rules(
        self, endpoint: str, user_config: UserRateLimit, config: RateLimitConfig
    ) -> Iterator[RateLimitRule]:
        """Enabled rules that match the endpoint, the user's own first, each list in priority order."""
        for rule in [*user_config.rules, *config.default_rules]:
            if rule.enabled and self._compile_pattern(rule.endpoint_pattern).match(endpoint):
                yield rule

    async def _get_config(self) -> RateLimitConfig:
        config_key = f"{self.prefix}config"
        config_data = await self.redis.get(config_key)

        config = _config_adapter.validate_json(config_data) if config_data else RateLimitConfig.get_default_config()
        overrides = await self.redis.hgetall(f"{self.prefix}user_overrides")
        config.user_overrides |= _overrides_adapter.validate_python(overrides)
        self._prepare_config(config)
        return config

    async def update_config(self, config: RateLimitConfig) -> None:
        config_key = f"{self.prefix}config"
        await self.redis.set(config_key, _config_adapter.dump_json(config))

    async def update_user_rate_limit(self, user_id: str, user_limit: UserRateLimit) -> None:
        """Store the override in its own hash field, so concurrent updates for different users can't undo each other."""
        await self.redis.hset(f"{self.prefix}user_overrides", user_id, _user_limit_adapter.dump_json(user_limit))

    async def get_user_rate_limit(self, user_id: str) -> UserRateLimit:
        """The user's override, or the neutral defaults when there is none."""
        return self._user_limit(await self._get_config(), user_id)

    @classmethod
    def _summary(cls, config: RateLimitConfig, user_id: str) -> UserRateLimitSummary:
        limit = cls._user_limit(config, user_id)
        return UserRateLimitSummary(
            user_id=user_id,
            has_custom_limits=(
                limit.bypass_rate_limit
                or not math.isclose(limit.global_multiplier, 1.0, rel_tol=1e-9, abs_tol=1e-12)
                or len(limit.rules) > 0
            ),
            bypass_rate_limit=limit.bypass_rate_limit,
            global_multiplier=limit.global_multiplier,
            rules_count=len(limit.rules),
        )

    async def get_override_summaries(self) -> list[UserRateLimitSummary]:
        """Summaries of the users with an override; every other user has the defaults."""
        config = await self._get_config()
        return [self._summary(config, user_id) for user_id in config.user_overrides]

    async def get_user_rate_limit_summary(self, user_id: str) -> UserRateLimitSummary:
        """Summary of the user's limits; a user without an override gets the defaults."""
        return self._summary(await self._get_config(), user_id)

    async def reset_user_limits(self, user_id: str) -> None:
        index_key = self._index_key(user_id)
        keys = await self.redis.smembers(index_key)
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(index_key)

    async def get_usage_stats(self, user_id: str) -> dict[str, EndpointUsageStats]:
        stats: dict[str, EndpointUsageStats] = {}
        index_key = self._index_key(user_id)
        keys = _keys_adapter.validate_python(await self.redis.smembers(index_key))
        if not keys:
            return stats

        config = await self._get_config()
        user_config = self._user_limit(config, user_id)

        for key in keys:
            algo, _, rest = key.removeprefix(self.prefix).partition(":")
            endpoint = rest.removeprefix(f"{user_id}:")

            if algo == "sw":
                count = await self.redis.zcard(key)
                limit = next(
                    (
                        int(rule.requests * user_config.global_multiplier)
                        for rule in self._matching_rules(endpoint, user_config, config)
                    ),
                    0,
                )
                remaining = max(0, limit - count)
                stats[endpoint] = EndpointUsageStats(algorithm=RateLimitAlgorithm.SLIDING_WINDOW, remaining=remaining)
            elif algo == "tb":
                bucket_data = await self.redis.get(key)
                if bucket_data:
                    bucket = json.loads(bucket_data)
                    stats[endpoint] = EndpointUsageStats(
                        algorithm=RateLimitAlgorithm.TOKEN_BUCKET, remaining=int(bucket.get("tokens", 0))
                    )
        return stats
