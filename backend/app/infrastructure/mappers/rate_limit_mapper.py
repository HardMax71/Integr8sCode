import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict

from app.domain.rate_limit import (
    EndpointGroup,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    RateLimitStatus,
    UserRateLimit,
)


class RateLimitRuleMapper:
    @staticmethod
    def to_dict(rule: RateLimitRule) -> Dict[str, Any]:
        return {
            "endpoint_pattern": rule.endpoint_pattern,
            "group": rule.group.value,
            "requests": rule.requests,
            "window_seconds": rule.window_seconds,
            "burst_multiplier": rule.burst_multiplier,
            "algorithm": rule.algorithm.value,
            "priority": rule.priority,
            "enabled": rule.enabled,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> RateLimitRule:
        return RateLimitRule(
            endpoint_pattern=data["endpoint_pattern"],
            group=EndpointGroup(data["group"]),
            requests=data["requests"],
            window_seconds=data["window_seconds"],
            burst_multiplier=data.get("burst_multiplier", 1.5),
            algorithm=RateLimitAlgorithm(data.get("algorithm", RateLimitAlgorithm.SLIDING_WINDOW)),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
        )


class UserRateLimitMapper:
    @staticmethod
    def to_dict(user_limit: UserRateLimit) -> Dict[str, Any]:
        rule_mapper = RateLimitRuleMapper()
        return {
            "user_id": user_limit.user_id,
            "bypass_rate_limit": user_limit.bypass_rate_limit,
            "global_multiplier": user_limit.global_multiplier,
            "rules": [rule_mapper.to_dict(rule) for rule in user_limit.rules],
            "created_at": user_limit.created_at.isoformat() if user_limit.created_at else None,
            "updated_at": user_limit.updated_at.isoformat() if user_limit.updated_at else None,
            "notes": user_limit.notes,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> UserRateLimit:
        rule_mapper = RateLimitRuleMapper()

        created_at = data.get("created_at")
        if created_at and isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not created_at:
            created_at = datetime.now(timezone.utc)

        updated_at = data.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif not updated_at:
            updated_at = datetime.now(timezone.utc)

        return UserRateLimit(
            user_id=data["user_id"],
            bypass_rate_limit=data.get("bypass_rate_limit", False),
            global_multiplier=data.get("global_multiplier", 1.0),
            rules=[rule_mapper.from_dict(rule_data) for rule_data in data.get("rules", [])],
            created_at=created_at,
            updated_at=updated_at,
            notes=data.get("notes"),
        )

    @staticmethod
    def model_dump(user_limit: UserRateLimit) -> Dict[str, Any]:
        """Pydantic-compatible method for serialization."""
        return UserRateLimitMapper.to_dict(user_limit)


class RateLimitConfigMapper:
    @staticmethod
    def to_dict(config: RateLimitConfig) -> Dict[str, Any]:
        rule_mapper = RateLimitRuleMapper()
        user_mapper = UserRateLimitMapper()
        return {
            "default_rules": [rule_mapper.to_dict(rule) for rule in config.default_rules],
            "user_overrides": {
                uid: user_mapper.to_dict(user_limit) for uid, user_limit in config.user_overrides.items()
            },
            "global_enabled": config.global_enabled,
            "redis_ttl": config.redis_ttl,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> RateLimitConfig:
        rule_mapper = RateLimitRuleMapper()
        user_mapper = UserRateLimitMapper()
        return RateLimitConfig(
            default_rules=[rule_mapper.from_dict(rule_data) for rule_data in data.get("default_rules", [])],
            user_overrides={
                uid: user_mapper.from_dict(user_data) for uid, user_data in data.get("user_overrides", {}).items()
            },
            global_enabled=data.get("global_enabled", True),
            redis_ttl=data.get("redis_ttl", 3600),
        )

    @staticmethod
    def model_validate_json(json_str: str | bytes) -> RateLimitConfig:
        """Pydantic-compatible method for deserialization from JSON."""
        data = json.loads(json_str)
        return RateLimitConfigMapper.from_dict(data)

    @staticmethod
    def model_dump_json(config: RateLimitConfig) -> str:
        """Pydantic-compatible method for serialization to JSON."""
        return json.dumps(RateLimitConfigMapper.to_dict(config))


class RateLimitStatusMapper:
    @staticmethod
    def to_dict(status: RateLimitStatus) -> Dict[str, Any]:
        return asdict(status)
