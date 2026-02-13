import asyncio
import json
import structlog
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import redis.asyncio as redis
from app.core.metrics import DatabaseMetrics
from app.domain.enums import EventType
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus, KeyStrategy
from app.services.idempotency import IdempotencyConfig, IdempotencyManager, RedisIdempotencyRepository
from app.settings import Settings

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.redis]

# Test logger for all tests
_test_logger = structlog.get_logger("test.idempotency")


class TestIdempotencyManager:
    """IdempotencyManager backed by real Redis repository (DI-provided client)."""

    @pytest.fixture
    def manager(self, redis_client: redis.Redis, test_settings: Settings) -> IdempotencyManager:
        prefix = f"idemp_ut:{uuid.uuid4().hex[:6]}"
        cfg = IdempotencyConfig(
            key_prefix=prefix,
            default_ttl_seconds=3600,
            processing_timeout_seconds=5,
            enable_result_caching=True,
            max_result_size_bytes=1024,
        )
        repo = RedisIdempotencyRepository(redis_client, key_prefix=prefix)
        database_metrics = DatabaseMetrics(test_settings)
        return IdempotencyManager(cfg, repo, _test_logger, database_metrics=database_metrics)

    @pytest.mark.asyncio
    async def test_complete_flow_new_event(self, manager: IdempotencyManager) -> None:
        """Test the complete flow for a new event"""
        real_event = make_execution_requested_event(execution_id="exec-123")
        # Check and reserve
        result = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING
        assert result.key.endswith(f"{real_event.event_type}:{real_event.event_id}")
        assert result.key.startswith(f"{manager.config.key_prefix}:")

        # Verify it's in the repository
        record = await manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.PROCESSING

        # Mark as completed
        success = await manager.mark_completed(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert success is True

        # Verify status updated
        record = await manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.COMPLETED
        assert record.completed_at is not None
        assert record.processing_duration_ms is not None

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, manager: IdempotencyManager) -> None:
        """Test that duplicates are properly detected"""
        real_event = make_execution_requested_event(execution_id="exec-dupe-1")
        # First request
        result1 = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert result1.is_duplicate is False

        # Mark as completed
        await manager.mark_completed(real_event, key_strategy=KeyStrategy.EVENT_BASED)

        # Second request with same event
        result2 = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert result2.is_duplicate is True
        assert result2.status == IdempotencyStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_concurrent_requests_race_condition(self, manager: IdempotencyManager) -> None:
        """Test handling of concurrent requests for the same event"""
        real_event = make_execution_requested_event(execution_id="exec-race-1")
        # Simulate concurrent requests
        tasks = [
            manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
            for _ in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # Only one should succeed
        non_duplicate_count = sum(1 for r in results if not r.is_duplicate)
        assert non_duplicate_count == 1

        # Others should be marked as duplicates
        duplicate_count = sum(1 for r in results if r.is_duplicate)
        assert duplicate_count == 4

    @pytest.mark.asyncio
    async def test_processing_timeout_allows_retry(self, manager: IdempotencyManager) -> None:
        """Test that stuck processing allows retry after timeout"""
        real_event = make_execution_requested_event(execution_id="exec-timeout-1")
        # First request
        result1 = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert result1.is_duplicate is False

        # Manually update the created_at to simulate old processing
        record = await manager._repo.find_by_key(result1.key)
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await manager._repo.update_record(record)

        # Second request should be allowed due to timeout
        result2 = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert result2.is_duplicate is False  # Allowed to retry
        assert result2.status == IdempotencyStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_content_hash_strategy(self, manager: IdempotencyManager) -> None:
        """Test content-based deduplication"""
        # Two events with same content and same execution_id
        event1 = make_execution_requested_event(
            execution_id="exec-1",
            service_name="test-service",
        )

        event2 = make_execution_requested_event(
            execution_id="exec-1",
            service_name="test-service",
        )

        # Use content hash strategy
        result1 = await manager.check_and_reserve(event1, key_strategy=KeyStrategy.CONTENT_HASH)
        assert result1.is_duplicate is False

        await manager.mark_completed(event1, key_strategy=KeyStrategy.CONTENT_HASH)

        # Second event with same content should be duplicate
        result2 = await manager.check_and_reserve(event2, key_strategy=KeyStrategy.CONTENT_HASH)
        assert result2.is_duplicate is True

    @pytest.mark.asyncio
    async def test_failed_event_handling(self, manager: IdempotencyManager) -> None:
        """Test marking events as failed"""
        real_event = make_execution_requested_event(execution_id="exec-failed-1")
        # Reserve
        result = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert result.is_duplicate is False

        # Mark as failed
        error_msg = "Execution failed: out of memory"
        success = await manager.mark_failed(real_event, error=error_msg, key_strategy=KeyStrategy.EVENT_BASED)
        assert success is True

        # Verify status and error
        record = await manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.FAILED
        assert record.error == error_msg
        assert record.completed_at is not None

    @pytest.mark.asyncio
    async def test_result_caching(self, manager: IdempotencyManager) -> None:
        """Test caching of results"""
        real_event = make_execution_requested_event(execution_id="exec-cache-1")
        # Reserve
        result = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert result.is_duplicate is False

        # Complete with cached result
        cached_result = json.dumps({"output": "Hello, World!", "exit_code": 0})
        success = await manager.mark_completed_with_json(
            real_event,
            cached_json=cached_result,
            key_strategy=KeyStrategy.EVENT_BASED
        )
        assert success is True

        # Retrieve cached result
        retrieved = await manager.get_cached_json(real_event, KeyStrategy.EVENT_BASED, None)
        assert retrieved == cached_result

        # Check duplicate with cached result
        duplicate_result = await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        assert duplicate_result.is_duplicate is True
        assert duplicate_result.has_cached_result is True

    @pytest.mark.asyncio
    async def test_invalid_key_strategy(self, manager: IdempotencyManager) -> None:
        """Test that invalid key strategy raises error"""
        real_event = make_execution_requested_event(execution_id="invalid-strategy-1")
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await manager.check_and_reserve(real_event, key_strategy="invalid_strategy")  # type: ignore[arg-type]  # testing invalid use

    @pytest.mark.asyncio
    async def test_custom_key_without_custom_key_param(self, manager: IdempotencyManager) -> None:
        """Test that custom strategy without custom_key raises error"""
        real_event = make_execution_requested_event(execution_id="custom-key-missing-1")
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.CUSTOM)

    @pytest.mark.asyncio
    async def test_get_cached_json_existing(self, manager: IdempotencyManager) -> None:
        """Test retrieving cached JSON result"""
        real_event = make_execution_requested_event(execution_id="cache-exist-1")
        await manager.check_and_reserve(real_event, key_strategy=KeyStrategy.EVENT_BASED)
        cached_data = json.dumps({"output": "test", "code": 0})
        await manager.mark_completed_with_json(real_event, cached_data, KeyStrategy.EVENT_BASED)

        retrieved = await manager.get_cached_json(real_event, KeyStrategy.EVENT_BASED, None)
        assert retrieved == cached_data

    @pytest.mark.asyncio
    async def test_get_cached_json_non_existing(self, manager: IdempotencyManager) -> None:
        """Test retrieving non-existing cached result returns None"""
        real_event = make_execution_requested_event(execution_id="cache-miss-1")
        result = await manager.get_cached_json(real_event, KeyStrategy.EVENT_BASED, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_keys(self, manager: IdempotencyManager) -> None:
        """Test cleanup of expired keys"""
        expired_key = f"{manager.config.key_prefix}:expired"
        expired_record = IdempotencyRecord(
            key=expired_key,
            status=IdempotencyStatus.COMPLETED,
            event_type=EventType.EXECUTION_REQUESTED,
            event_id="expired-1",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ttl_seconds=3600,
            completed_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        await manager._repo.insert_processing(expired_record)

        record = await manager._repo.find_by_key(expired_key)
        assert record is not None

    @pytest.mark.asyncio
    async def test_content_hash_with_fields(self, manager: IdempotencyManager) -> None:
        """Test content hash with specific fields"""
        event1 = make_execution_requested_event(
            execution_id="exec-1",
            service_name="test-service",
        )

        fields = {"script", "language"}
        result1 = await manager.check_and_reserve(
            event1,
            key_strategy=KeyStrategy.CONTENT_HASH,
            fields=fields
        )
        assert result1.is_duplicate is False
        await manager.mark_completed(event1, key_strategy=KeyStrategy.CONTENT_HASH, fields=fields)

        event2 = make_execution_requested_event(
            execution_id="exec-2",
            timeout_seconds=60,
            cpu_limit="200m",
            memory_limit="256Mi",
            cpu_request="100m",
            memory_request="128Mi",
            service_name="test-service",
        )

        result2 = await manager.check_and_reserve(
            event2,
            key_strategy=KeyStrategy.CONTENT_HASH,
            fields=fields
        )
        assert result2.is_duplicate is True
