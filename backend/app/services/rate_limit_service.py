import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as redis

from app.core.metrics.rate_limit import RateLimitMetrics
from app.domain.rate_limit import RateLimitAlgorithm, RateLimitConfig, RateLimitRule, RateLimitStatus, UserRateLimit
from app.infrastructure.mappers.rate_limit_mapper import RateLimitConfigMapper
from app.settings import Settings


class RateLimitService:
    def __init__(self, redis_client: redis.Redis, settings: Settings, metrics: "RateLimitMetrics"):
        self.redis = redis_client
        self.settings = settings
        self.prefix = settings.RATE_LIMIT_REDIS_PREFIX
        self.metrics = metrics

        # Patterns to match IDs and replace with *
        self._uuid_pattern = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
        self._id_pattern = re.compile(r'/[0-9a-zA-Z]{20,}(?=/|$)')
    
    def _normalize_endpoint(self, endpoint: str) -> str:
        normalized = self._uuid_pattern.sub('*', endpoint)
        normalized = self._id_pattern.sub('/*', normalized)
        return normalized

    async def check_rate_limit(
            self,
            user_id: str,
            endpoint: str,
            config: Optional[RateLimitConfig] = None,
            username: Optional[str] = None
    ) -> RateLimitStatus:
        start_time = time.time()
        is_ip_based = user_id.startswith("ip:")
        identifier_type = "ip" if is_ip_based else "user"

        # For metrics, use username if provided, otherwise use user_id
        # IP addresses remain as-is (without ip: prefix)
        if is_ip_based:
            clean_identifier = user_id[3:]  # Remove 'ip:' prefix for metrics
        else:
            clean_identifier = username if username else user_id

        # Normalize endpoint for metrics
        normalized_endpoint = self._normalize_endpoint(endpoint)
        
        try:
            # Track IP vs User checks early (doesn't need algorithm)
            if is_ip_based:
                self.metrics.ip_checks.add(1, {
                    "identifier": clean_identifier,
                    "endpoint": normalized_endpoint
                })
            else:
                self.metrics.user_checks.add(1, {
                    "identifier": clean_identifier,
                    "endpoint": normalized_endpoint
                })

            if not self.settings.RATE_LIMIT_ENABLED:
                # Track request when rate limiting is disabled
                self.metrics.requests_total.add(1, {
                    "identifier": clean_identifier,
                    "identifier_type": identifier_type,
                    "endpoint": normalized_endpoint,
                    "algorithm": "disabled"
                })
                return RateLimitStatus(
                    allowed=True,
                    limit=999999,
                    remaining=999999,
                    reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    retry_after=None,
                    matched_rule=None,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW
                )

            if config is None:
                redis_start = time.time()
                try:
                    config = await self._get_config()
                except Exception as e:
                    self.metrics.config_errors.add(1, {"error_type": type(e).__name__})
                    raise
                finally:
                    redis_duration = (time.time() - redis_start) * 1000
                    self.metrics.redis_duration.record(redis_duration, {
                        "operation": "get_config"
                    })

            if not config.global_enabled:
                return RateLimitStatus(
                    allowed=True,
                    limit=999999,
                    remaining=999999,
                    reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    retry_after=None,
                    matched_rule=None,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW
                )

            # Check user overrides
            user_config = config.user_overrides.get(str(user_id))
            ### HINT: For simplicity, make this check = True during load tests ###
            if user_config and user_config.bypass_rate_limit:
                # Track both bypass and total requests
                self.metrics.bypass.add(1, {
                    "identifier": clean_identifier,
                    "endpoint": normalized_endpoint
                })
                self.metrics.requests_total.add(1, {
                    "identifier": clean_identifier,
                    "identifier_type": identifier_type,
                    "endpoint": normalized_endpoint,
                    "algorithm": "bypassed"
                })
                return RateLimitStatus(
                    allowed=True,
                    limit=999999,
                    remaining=999999,
                    reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    retry_after=None,
                    matched_rule=None,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW
                )

            # Find matching rule
            rule = self._find_matching_rule(endpoint, user_config, config)
            if not rule:
                # Track request with default algorithm when no rule matches
                self.metrics.requests_total.add(1, {
                    "identifier": clean_identifier,
                    "identifier_type": identifier_type,
                    "endpoint": normalized_endpoint,
                    "algorithm": "no_limit"
                })
                return RateLimitStatus(
                    allowed=True,
                    limit=999999,
                    remaining=999999,
                    reset_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    retry_after=None,
                    matched_rule=None,
                    algorithm=RateLimitAlgorithm.SLIDING_WINDOW
                )

            # Apply user multiplier if exists
            effective_limit = rule.requests
            multiplier = 1.0
            if user_config:
                multiplier = user_config.global_multiplier
                effective_limit = int(effective_limit * multiplier)

            # Track total requests with algorithm
            self.metrics.requests_total.add(1, {
                "identifier": clean_identifier,
                "identifier_type": identifier_type,
                "endpoint": normalized_endpoint,
                "algorithm": rule.algorithm.value
            })

            # Record window size
            self.metrics.window_size.record(rule.window_seconds, {
                "endpoint": normalized_endpoint,
                "algorithm": rule.algorithm.value
            })

            # Check rate limit based on algorithm
            algo_start = time.time()
            if rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                status = await self._check_sliding_window(
                    user_id, endpoint, effective_limit, rule.window_seconds, rule
                )
            elif rule.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                status = await self._check_token_bucket(
                    user_id, endpoint, effective_limit, rule.window_seconds,
                    rule.burst_multiplier, rule
                )
            else:
                # Default to sliding window
                status = await self._check_sliding_window(
                    user_id, endpoint, effective_limit, rule.window_seconds, rule
                )

            algo_duration = (time.time() - algo_start) * 1000
            self.metrics.algorithm_duration.record(algo_duration, {
                "algorithm": rule.algorithm.value,
                "endpoint": normalized_endpoint
            })

            # Record comprehensive metrics
            labels = {
                "identifier": clean_identifier,
                "identifier_type": identifier_type,
                "endpoint": normalized_endpoint,
                "algorithm": rule.algorithm.value,
                "group": rule.group.value,
                "priority": str(rule.priority),
                "multiplier": str(multiplier)
            }

            if status.allowed:
                self.metrics.allowed.add(1, labels)
            else:
                self.metrics.rejected.add(1, labels)

            # Record remaining requests
            self.metrics.remaining.record(status.remaining, labels)

            # Calculate and record quota usage percentage
            if status.limit > 0:
                quota_used = ((status.limit - status.remaining) / status.limit) * 100
                self.metrics.quota_usage.record(quota_used, labels)

            return status

        except Exception as e:
            self.metrics.redis_errors.add(1, {
                "error_type": type(e).__name__,
                "operation": "check_rate_limit"
            })
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self.metrics.check_duration.record(
                duration_ms,
                {
                    "endpoint": normalized_endpoint,
                    "identifier_type": identifier_type
                }
            )

    async def _check_sliding_window(
            self,
            user_id: str,
            endpoint: str,
            limit: int,
            window_seconds: int,
            rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}sw:{user_id}:{endpoint}"
        now = time.time()
        window_start = now - window_seconds

        normalized_endpoint = self._normalize_endpoint(endpoint)

        redis_start = time.time()
        try:
            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds * 2)
            results = await pipe.execute()
        except Exception as e:
            self.metrics.redis_errors.add(1, {
                "error_type": type(e).__name__,
                "operation": "sliding_window_pipeline"
            })
            raise
        finally:
            redis_duration = (time.time() - redis_start) * 1000
            self.metrics.redis_duration.record(redis_duration, {
                "operation": "sliding_window",
                "endpoint": normalized_endpoint
            })

        count = results[2]
        remaining = max(0, limit - count)

        if count > limit:
            # Calculate retry after
            redis_start = time.time()
            try:
                oldest_timestamp = await self.redis.zrange(key, 0, 0, withscores=True)
            finally:
                redis_duration = (time.time() - redis_start) * 1000
                self.metrics.redis_duration.record(redis_duration, {
                    "operation": "get_oldest_timestamp"
                })

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
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )

        return RateLimitStatus(
            allowed=True,
            limit=limit,
            remaining=remaining,
            reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
            retry_after=None,
            matched_rule=rule.endpoint_pattern,
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW
        )

    async def _check_token_bucket(
            self,
            user_id: str,
            endpoint: str,
            limit: int,
            window_seconds: int,
            burst_multiplier: float,
            rule: RateLimitRule
    ) -> RateLimitStatus:
        key = f"{self.prefix}tb:{user_id}:{endpoint}"
        max_tokens = int(limit * burst_multiplier)
        refill_rate = limit / window_seconds

        normalized_endpoint = self._normalize_endpoint(endpoint)

        now = time.time()

        # Get current bucket state
        redis_start = time.time()
        try:
            bucket_data = await self.redis.get(key)
        except Exception as e:
            self.metrics.redis_errors.add(1, {
                "error_type": type(e).__name__,
                "operation": "token_bucket_get"
            })
            raise
        finally:
            redis_duration = (time.time() - redis_start) * 1000
            self.metrics.redis_duration.record(redis_duration, {
                "operation": "token_bucket_get",
                "endpoint": normalized_endpoint
            })

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
        self.metrics.token_bucket_tokens.record(tokens, {
            "endpoint": normalized_endpoint,
            "identifier": user_id
        })
        self.metrics.token_bucket_refill_rate.record(refill_rate, {
            "endpoint": normalized_endpoint
        })

        # Try to consume a token
        if tokens >= 1:
            tokens -= 1
            bucket = {
                "tokens": tokens,
                "last_refill": now
            }

            redis_start = time.time()
            try:
                await self.redis.setex(
                    key,
                    window_seconds * 2,
                    json.dumps(bucket)
                )
            except Exception as e:
                self.metrics.redis_errors.add(1, {
                    "error_type": type(e).__name__,
                    "operation": "token_bucket_set"
                })
                raise
            finally:
                redis_duration = (time.time() - redis_start) * 1000
                self.metrics.redis_duration.record(redis_duration, {
                    "operation": "token_bucket_set",
                    "endpoint": normalized_endpoint
                })

            return RateLimitStatus(
                allowed=True,
                limit=limit,
                remaining=int(tokens),
                reset_at=datetime.fromtimestamp(now + window_seconds, timezone.utc),
                retry_after=None,
                matched_rule=rule.endpoint_pattern,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET
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
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET
            )

    def _find_matching_rule(
            self,
            endpoint: str,
            user_config: Optional[UserRateLimit],
            global_config: RateLimitConfig
    ) -> Optional[RateLimitRule]:
        rules = []

        # Add user-specific rules
        if user_config and user_config.rules:
            rules.extend(user_config.rules)

        # Add global default rules
        rules.extend(global_config.default_rules)

        # Sort by priority (descending) and find first match
        rules.sort(key=lambda r: r.priority, reverse=True)

        for rule in rules:
            if rule.enabled and re.match(rule.endpoint_pattern, endpoint):
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
                mapper.model_dump_json(config)
            )

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

        redis_start = time.time()
        try:
            await self.redis.setex(
                config_key,
                300,  # Cache for 5 minutes
                mapper.model_dump_json(config)
            )
        except Exception as e:
            self.metrics.redis_errors.add(1, {
                "error_type": type(e).__name__,
                "operation": "update_config"
            })
            raise
        finally:
            redis_duration = (time.time() - redis_start) * 1000
            self.metrics.redis_duration.record(redis_duration, {
                "operation": "update_config"
            })

        # Update configuration metrics - just record the absolute values
        active_rules_count = len([r for r in config.default_rules if r.enabled])
        custom_users_count = len(config.user_overrides)
        bypass_users_count = len([u for u in config.user_overrides.values() if u.bypass_rate_limit])

        # Record current values (histograms will track the distribution)
        self.metrics.active_rules.record(active_rules_count)
        self.metrics.custom_users.record(custom_users_count)
        self.metrics.bypass_users.record(bypass_users_count)

    async def update_user_rate_limit(
            self,
            user_id: str,
            user_limit: UserRateLimit
    ) -> None:
        config = await self._get_config()
        config.user_overrides[str(user_id)] = user_limit
        await self.update_config(config)

    async def get_user_rate_limit(self, user_id: str) -> Optional[UserRateLimit]:
        config = await self._get_config()
        return config.user_overrides.get(str(user_id))

    async def reset_user_limits(self, user_id: str) -> None:
        pattern = f"{self.prefix}*:{user_id}:*"
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=pattern,
                count=100
            )

            if keys:
                await self.redis.delete(*keys)

            if cursor == 0:
                break

    async def get_usage_stats(self, user_id: str) -> dict:
        stats = {}
        pattern = f"{self.prefix}*:{user_id}:*"
        cursor = 0

        while True:
            cursor, keys = await self.redis.scan(
                cursor,
                match=pattern,
                count=100
            )

            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                parts = key_str.split(":")
                if len(parts) >= 4:
                    endpoint = ":".join(parts[3:])

                    if parts[1] == "sw":
                        # Sliding window
                        count = await self.redis.zcard(key)
                        stats[endpoint] = {"count": count, "algorithm": "sliding_window"}
                    elif parts[1] == "tb":
                        # Token bucket
                        bucket_data = await self.redis.get(key)
                        if bucket_data:
                            bucket = json.loads(bucket_data)
                            stats[endpoint] = {
                                "tokens_remaining": bucket["tokens"],
                                "algorithm": "token_bucket"
                            }

            if cursor == 0:
                break

        return stats
