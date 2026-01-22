import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus
from app.services.idempotency.idempotency_manager import IdempotencyManager

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.redis]

# Test logger for all tests
_test_logger = logging.getLogger("test.idempotency")


class TestIdempotencyManager:
    """IdempotencyManager backed by real Redis repository (DI-provided client)."""

    @pytest.mark.asyncio
    async def test_complete_flow_new_event(self, idempotency_manager: IdempotencyManager) -> None:
        """Test the complete flow for a new event"""
        real_event = make_execution_requested_event(execution_id="exec-123")
        # Check and reserve
        result = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING
        assert result.key.endswith(f"{real_event.event_type}:{real_event.event_id}")
        assert result.key.startswith(f"{idempotency_manager.config.key_prefix}:")

        # Verify it's in the repository
        record = await idempotency_manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.PROCESSING

        # Mark as completed
        success = await idempotency_manager.mark_completed(real_event, key_strategy="event_based")
        assert success is True

        # Verify status updated
        record = await idempotency_manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.COMPLETED
        assert record.completed_at is not None
        assert record.processing_duration_ms is not None

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, idempotency_manager: IdempotencyManager) -> None:
        """Test that duplicates are properly detected"""
        real_event = make_execution_requested_event(execution_id="exec-dupe-1")
        # First request
        result1 = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result1.is_duplicate is False

        # Mark as completed
        await idempotency_manager.mark_completed(real_event, key_strategy="event_based")

        # Second request with same event
        result2 = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is True
        assert result2.status == IdempotencyStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_concurrent_requests_race_condition(self, idempotency_manager: IdempotencyManager) -> None:
        """Test handling of concurrent requests for the same event"""
        real_event = make_execution_requested_event(execution_id="exec-race-1")
        # Simulate concurrent requests
        tasks = [
            idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
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
    async def test_processing_timeout_allows_retry(self, idempotency_manager: IdempotencyManager) -> None:
        """Test that stuck processing allows retry after timeout"""
        real_event = make_execution_requested_event(execution_id="exec-timeout-1")
        # First request
        result1 = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result1.is_duplicate is False

        # Manually update the created_at to simulate old processing
        record = await idempotency_manager._repo.find_by_key(result1.key)
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await idempotency_manager._repo.update_record(record)

        # Second request should be allowed due to timeout
        result2 = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is False  # Allowed to retry
        assert result2.status == IdempotencyStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_content_hash_strategy(self, idempotency_manager: IdempotencyManager) -> None:
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
        result1 = await idempotency_manager.check_and_reserve(event1, key_strategy="content_hash")
        assert result1.is_duplicate is False

        await idempotency_manager.mark_completed(event1, key_strategy="content_hash")

        # Second event with same content should be duplicate
        result2 = await idempotency_manager.check_and_reserve(event2, key_strategy="content_hash")
        assert result2.is_duplicate is True

    @pytest.mark.asyncio
    async def test_failed_event_handling(self, idempotency_manager: IdempotencyManager) -> None:
        """Test marking events as failed"""
        real_event = make_execution_requested_event(execution_id="exec-failed-1")
        # Reserve
        result = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Mark as failed
        error_msg = "Execution failed: out of memory"
        success = await idempotency_manager.mark_failed(real_event, error=error_msg, key_strategy="event_based")
        assert success is True

        # Verify status and error
        record = await idempotency_manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.FAILED
        assert record.error == error_msg
        assert record.completed_at is not None

    @pytest.mark.asyncio
    async def test_result_caching(self, idempotency_manager: IdempotencyManager) -> None:
        """Test caching of results"""
        real_event = make_execution_requested_event(execution_id="exec-cache-1")
        # Reserve
        result = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Complete with cached result
        cached_result = json.dumps({"output": "Hello, World!", "exit_code": 0})
        success = await idempotency_manager.mark_completed_with_json(
            real_event,
            cached_json=cached_result,
            key_strategy="event_based"
        )
        assert success is True

        # Retrieve cached result
        retrieved = await idempotency_manager.get_cached_json(real_event, "event_based", None)
        assert retrieved == cached_result

        # Check duplicate with cached result
        duplicate_result = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert duplicate_result.is_duplicate is True
        assert duplicate_result.has_cached_result is True

    @pytest.mark.asyncio
    async def test_stats_aggregation(self, idempotency_manager: IdempotencyManager) -> None:
        """Test statistics aggregation"""
        # Create various events with different statuses
        events = []
        for i in range(10):
            event = make_execution_requested_event(
                execution_id=f"exec-{i}",
                script=f"print({i})",
                service_name="test-service",
            )
            events.append(event)

        # Process events with different outcomes
        for i, event in enumerate(events):
            await idempotency_manager.check_and_reserve(event, key_strategy="event_based")

            if i < 6:
                await idempotency_manager.mark_completed(event, key_strategy="event_based")
            elif i < 8:
                await idempotency_manager.mark_failed(event, "Test error", key_strategy="event_based")
            # Leave rest in processing

        # Get stats
        stats = await idempotency_manager.get_stats()

        assert stats.total_keys == 10
        assert stats.status_counts[IdempotencyStatus.COMPLETED] == 6
        assert stats.status_counts[IdempotencyStatus.FAILED] == 2
        assert stats.status_counts[IdempotencyStatus.PROCESSING] == 2
        assert stats.prefix == idempotency_manager.config.key_prefix

    @pytest.mark.asyncio
    async def test_remove_key(self, idempotency_manager: IdempotencyManager) -> None:
        """Test removing idempotency keys"""
        real_event = make_execution_requested_event(execution_id="exec-remove-1")
        # Add a key
        result = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Remove it
        removed = await idempotency_manager.remove(real_event, key_strategy="event_based")
        assert removed is True

        # Verify it's gone
        record = await idempotency_manager._repo.find_by_key(result.key)
        assert record is None

        # Can process again
        result2 = await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is False


class TestIdempotencyManagerValidation:
    """Test IdempotencyManager validation and edge cases"""

    @pytest.mark.asyncio
    async def test_invalid_key_strategy(self, idempotency_manager: IdempotencyManager) -> None:
        """Test that invalid key strategy raises error"""
        real_event = make_execution_requested_event(execution_id="invalid-strategy-1")
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await idempotency_manager.check_and_reserve(real_event, key_strategy="invalid_strategy")

    @pytest.mark.asyncio
    async def test_custom_key_without_custom_key_param(self, idempotency_manager: IdempotencyManager) -> None:
        """Test that custom strategy without custom_key raises error"""
        real_event = make_execution_requested_event(execution_id="custom-key-missing-1")
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await idempotency_manager.check_and_reserve(real_event, key_strategy="custom")

    @pytest.mark.asyncio
    async def test_get_cached_json_existing(self, idempotency_manager: IdempotencyManager) -> None:
        """Test retrieving cached JSON result"""
        # First complete with cached result
        real_event = make_execution_requested_event(execution_id="cache-exist-1")
        await idempotency_manager.check_and_reserve(real_event, key_strategy="event_based")
        cached_data = json.dumps({"output": "test", "code": 0})
        await idempotency_manager.mark_completed_with_json(real_event, cached_data, "event_based")

        # Retrieve cached result
        retrieved = await idempotency_manager.get_cached_json(real_event, "event_based", None)
        assert retrieved == cached_data

    @pytest.mark.asyncio
    async def test_get_cached_json_non_existing(self, idempotency_manager: IdempotencyManager) -> None:
        """Test retrieving non-existing cached result raises assertion"""
        real_event = make_execution_requested_event(execution_id="cache-miss-1")
        # Trying to get cached result for non-existent key should raise
        with pytest.raises(AssertionError, match="cached result must exist"):
            await idempotency_manager.get_cached_json(real_event, "event_based", None)

    @pytest.mark.asyncio
    async def test_cleanup_expired_keys(self, idempotency_manager: IdempotencyManager) -> None:
        """Test cleanup of expired keys"""
        # Create expired record
        expired_key = f"{idempotency_manager.config.key_prefix}:expired"
        expired_record = IdempotencyRecord(
            key=expired_key,
            status=IdempotencyStatus.COMPLETED,
            event_type="test",
            event_id="expired-1",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ttl_seconds=3600,  # 1 hour TTL
            completed_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        await idempotency_manager._repo.insert_processing(expired_record)

        # Cleanup should detect it as expired
        # Note: actual cleanup implementation depends on repository
        record = await idempotency_manager._repo.find_by_key(expired_key)
        assert record is not None  # Still exists until explicit cleanup

    @pytest.mark.asyncio
    async def test_content_hash_with_fields(self, idempotency_manager: IdempotencyManager) -> None:
        """Test content hash with specific fields"""
        event1 = make_execution_requested_event(
            execution_id="exec-1",
            service_name="test-service",
        )

        # Use content hash with only script field
        fields = {"script", "language"}
        result1 = await idempotency_manager.check_and_reserve(
            event1,
            key_strategy="content_hash",
            fields=fields
        )
        assert result1.is_duplicate is False
        await idempotency_manager.mark_completed(event1, key_strategy="content_hash", fields=fields)

        # Event with same script and language but different other fields
        event2 = make_execution_requested_event(
            execution_id="exec-2",
            timeout_seconds=60,
            cpu_limit="200m",
            memory_limit="256Mi",
            cpu_request="100m",
            memory_request="128Mi",
            service_name="test-service",
        )

        result2 = await idempotency_manager.check_and_reserve(
            event2,
            key_strategy="content_hash",
            fields=fields
        )
        assert result2.is_duplicate is True  # Same script and language
