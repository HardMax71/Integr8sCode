"""Extended tests for rate limit mapper to achieve 95%+ coverage."""

from datetime import datetime, timezone

import pytest
from app.domain.rate_limit import (
    EndpointGroup,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitRule,
    UserRateLimit,
)
from app.infrastructure.mappers.rate_limit_mapper import (
    RateLimitConfigMapper,
    RateLimitRuleMapper,
    UserRateLimitMapper,
)


@pytest.fixture
def sample_rule():
    """Create a sample rate limit rule."""
    return RateLimitRule(
        endpoint_pattern="/api/*",
        group=EndpointGroup.PUBLIC,
        requests=100,
        window_seconds=60,
        burst_multiplier=2.0,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        priority=10,
        enabled=True,
    )


@pytest.fixture
def sample_user_limit(sample_rule):
    """Create a sample user rate limit."""
    return UserRateLimit(
        user_id="user-123",
        bypass_rate_limit=False,
        global_multiplier=1.5,
        rules=[sample_rule],
        created_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        notes="Test user with custom limits",
    )


class TestUserRateLimitMapper:
    """Test UserRateLimitMapper with focus on uncovered branches."""

    def test_from_dict_without_created_at(self):
        """Test creating user rate limit without created_at field (lines 65-66)."""
        data = {
            "user_id": "user-test",
            "bypass_rate_limit": True,
            "global_multiplier": 2.0,
            "rules": [],
            "created_at": None,  # Explicitly None
            "updated_at": "2024-01-15T10:00:00",
            "notes": "Test without created_at",
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-test"
        # Should default to current time
        assert user_limit.created_at is not None
        assert isinstance(user_limit.created_at, datetime)

    def test_from_dict_without_updated_at(self):
        """Test creating user rate limit without updated_at field (lines 71-72)."""
        data = {
            "user_id": "user-test2",
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [],
            "created_at": "2024-01-15T09:00:00",
            "updated_at": None,  # Explicitly None
            "notes": "Test without updated_at",
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-test2"
        # Should default to current time
        assert user_limit.updated_at is not None
        assert isinstance(user_limit.updated_at, datetime)

    def test_from_dict_missing_timestamps(self):
        """Test creating user rate limit with missing timestamp fields."""
        data = {
            "user_id": "user-test3",
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [],
            # No created_at or updated_at fields at all
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-test3"
        # Both should default to current time
        assert user_limit.created_at is not None
        assert user_limit.updated_at is not None
        assert isinstance(user_limit.created_at, datetime)
        assert isinstance(user_limit.updated_at, datetime)

    def test_from_dict_with_empty_string_timestamps(self):
        """Test creating user rate limit with empty string timestamps."""
        data = {
            "user_id": "user-test4",
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [],
            "created_at": "",  # Empty string (falsy)
            "updated_at": "",  # Empty string (falsy)
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-test4"
        # Both should default to current time when falsy
        assert user_limit.created_at is not None
        assert user_limit.updated_at is not None

    def test_from_dict_with_zero_timestamps(self):
        """Test creating user rate limit with zero/falsy timestamps."""
        data = {
            "user_id": "user-test5",
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [],
            "created_at": 0,  # Falsy number
            "updated_at": 0,  # Falsy number
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-test5"
        # Both should default to current time when falsy
        assert user_limit.created_at is not None
        assert user_limit.updated_at is not None

    def test_model_dump(self, sample_user_limit):
        """Test model_dump method (line 87)."""
        result = UserRateLimitMapper.model_dump(sample_user_limit)

        assert result["user_id"] == "user-123"
        assert result["bypass_rate_limit"] is False
        assert result["global_multiplier"] == 1.5
        assert len(result["rules"]) == 1
        assert result["notes"] == "Test user with custom limits"
        # Check it's the same as to_dict
        assert result == UserRateLimitMapper.to_dict(sample_user_limit)

    def test_model_dump_with_minimal_data(self):
        """Test model_dump with minimal user rate limit."""
        minimal_limit = UserRateLimit(
            user_id="minimal-user",
            bypass_rate_limit=False,
            global_multiplier=1.0,
            rules=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            notes=None,
        )

        result = UserRateLimitMapper.model_dump(minimal_limit)

        assert result["user_id"] == "minimal-user"
        assert result["bypass_rate_limit"] is False
        assert result["global_multiplier"] == 1.0
        assert result["rules"] == []
        assert result["notes"] is None

    def test_from_dict_with_datetime_objects(self):
        """Test from_dict when timestamps are already datetime objects."""
        now = datetime.now(timezone.utc)
        data = {
            "user_id": "user-datetime",
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [],
            "created_at": now,  # Already a datetime
            "updated_at": now,  # Already a datetime
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-datetime"
        assert user_limit.created_at == now
        assert user_limit.updated_at == now

    def test_from_dict_with_mixed_timestamp_types(self):
        """Test from_dict with one string and one None timestamp."""
        data = {
            "user_id": "user-mixed",
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [],
            "created_at": "2024-01-15T10:00:00",  # String
            "updated_at": None,  # None
        }

        user_limit = UserRateLimitMapper.from_dict(data)

        assert user_limit.user_id == "user-mixed"
        assert user_limit.created_at.year == 2024
        assert user_limit.created_at.month == 1
        assert user_limit.created_at.day == 15
        assert user_limit.updated_at is not None  # Should be set to current time


class TestRateLimitRuleMapper:
    """Additional tests for RateLimitRuleMapper."""

    def test_from_dict_with_defaults(self):
        """Test creating rule from dict with minimal data (using defaults)."""
        data = {
            "endpoint_pattern": "/api/test",
            "group": "public",
            "requests": 50,
            "window_seconds": 30,
            # Missing optional fields
        }

        rule = RateLimitRuleMapper.from_dict(data)

        assert rule.endpoint_pattern == "/api/test"
        assert rule.group == EndpointGroup.PUBLIC
        assert rule.requests == 50
        assert rule.window_seconds == 30
        # Check defaults
        assert rule.burst_multiplier == 1.5
        assert rule.algorithm == RateLimitAlgorithm.SLIDING_WINDOW
        assert rule.priority == 0
        assert rule.enabled is True


class TestRateLimitConfigMapper:
    """Additional tests for RateLimitConfigMapper."""

    def test_model_validate_json(self):
        """Test model_validate_json method."""
        json_str = """
        {
            "default_rules": [
                {
                    "endpoint_pattern": "/api/*",
                    "group": "public",
                    "requests": 100,
                    "window_seconds": 60,
                    "burst_multiplier": 1.5,
                    "algorithm": "sliding_window",
                    "priority": 0,
                    "enabled": true
                }
            ],
            "user_overrides": {
                "user-123": {
                    "user_id": "user-123",
                    "bypass_rate_limit": true,
                    "global_multiplier": 2.0,
                    "rules": [],
                    "created_at": null,
                    "updated_at": null,
                    "notes": "VIP user"
                }
            },
            "global_enabled": true,
            "redis_ttl": 7200
        }
        """

        config = RateLimitConfigMapper.model_validate_json(json_str)

        assert len(config.default_rules) == 1
        assert config.default_rules[0].endpoint_pattern == "/api/*"
        assert "user-123" in config.user_overrides
        assert config.user_overrides["user-123"].bypass_rate_limit is True
        assert config.global_enabled is True
        assert config.redis_ttl == 7200

    def test_model_validate_json_bytes(self):
        """Test model_validate_json with bytes input."""
        json_bytes = b'{"default_rules": [], "user_overrides": {}, "global_enabled": false, "redis_ttl": 3600}'

        config = RateLimitConfigMapper.model_validate_json(json_bytes)

        assert config.default_rules == []
        assert config.user_overrides == {}
        assert config.global_enabled is False
        assert config.redis_ttl == 3600

    def test_model_dump_json(self):
        """Test model_dump_json method."""
        config = RateLimitConfig(
            default_rules=[
                RateLimitRule(
                    endpoint_pattern="/test",
                    group=EndpointGroup.ADMIN,
                    requests=1000,
                    window_seconds=60,
                )
            ],
            user_overrides={},
            global_enabled=True,
            redis_ttl=3600,
        )

        json_str = RateLimitConfigMapper.model_dump_json(config)

        assert isinstance(json_str, str)
        # Parse it back to verify
        import json
        data = json.loads(json_str)
        assert len(data["default_rules"]) == 1
        assert data["default_rules"][0]["endpoint_pattern"] == "/test"
        assert data["global_enabled"] is True
        assert data["redis_ttl"] == 3600
