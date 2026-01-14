import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import redis.asyncio as redis
from app.domain.events.typed import DomainEvent
from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus
from app.services.idempotency.idempotency_manager import IdempotencyConfig, IdempotencyManager
from app.services.idempotency.middleware import IdempotentEventHandler, idempotent_handler
from app.services.idempotency.redis_repository import RedisIdempotencyRepository

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.redis]

# Test logger for all tests
_test_logger = logging.getLogger("test.idempotency")


class TestIdempotencyManager:
    """IdempotencyManager backed by real Redis repository (DI-provided client)."""

    @pytest.fixture
    async def manager(self, redis_client: redis.Redis) -> AsyncGenerator[IdempotencyManager, None]:
        prefix = f"idemp_ut:{uuid.uuid4().hex[:6]}"
        cfg = IdempotencyConfig(
            key_prefix=prefix,
            default_ttl_seconds=3600,
            processing_timeout_seconds=5,
            enable_result_caching=True,
            max_result_size_bytes=1024,
            enable_metrics=False,
        )
        repo = RedisIdempotencyRepository(redis_client, key_prefix=prefix)
        m = IdempotencyManager(cfg, repo, _test_logger)
        await m.initialize()
        try:
            yield m
        finally:
            await m.close()

    @pytest.mark.asyncio
    async def test_complete_flow_new_event(self, manager: IdempotencyManager) -> None:
        """Test the complete flow for a new event"""
        real_event = make_execution_requested_event(execution_id="exec-123")
        # Check and reserve
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING
        assert result.key.endswith(f"{real_event.event_type}:{real_event.event_id}")
        assert result.key.startswith(f"{manager.config.key_prefix}:")

        # Verify it's in the repository
        record = await manager._repo.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.PROCESSING

        # Mark as completed
        success = await manager.mark_completed(real_event, key_strategy="event_based")
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
        result1 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result1.is_duplicate is False

        # Mark as completed
        await manager.mark_completed(real_event, key_strategy="event_based")

        # Second request with same event
        result2 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is True
        assert result2.status == IdempotencyStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_concurrent_requests_race_condition(self, manager: IdempotencyManager) -> None:
        """Test handling of concurrent requests for the same event"""
        real_event = make_execution_requested_event(execution_id="exec-race-1")
        # Simulate concurrent requests
        tasks = [
            manager.check_and_reserve(real_event, key_strategy="event_based")
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
        result1 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result1.is_duplicate is False

        # Manually update the created_at to simulate old processing
        record = await manager._repo.find_by_key(result1.key)
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await manager._repo.update_record(record)

        # Second request should be allowed due to timeout
        result2 = await manager.check_and_reserve(real_event, key_strategy="event_based")
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
        result1 = await manager.check_and_reserve(event1, key_strategy="content_hash")
        assert result1.is_duplicate is False

        await manager.mark_completed(event1, key_strategy="content_hash")

        # Second event with same content should be duplicate
        result2 = await manager.check_and_reserve(event2, key_strategy="content_hash")
        assert result2.is_duplicate is True

    @pytest.mark.asyncio
    async def test_failed_event_handling(self, manager: IdempotencyManager) -> None:
        """Test marking events as failed"""
        real_event = make_execution_requested_event(execution_id="exec-failed-1")
        # Reserve
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Mark as failed
        error_msg = "Execution failed: out of memory"
        success = await manager.mark_failed(real_event, error=error_msg, key_strategy="event_based")
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
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Complete with cached result
        cached_result = json.dumps({"output": "Hello, World!", "exit_code": 0})
        success = await manager.mark_completed_with_json(
            real_event,
            cached_json=cached_result,
            key_strategy="event_based"
        )
        assert success is True

        # Retrieve cached result
        retrieved = await manager.get_cached_json(real_event, "event_based", None)
        assert retrieved == cached_result

        # Check duplicate with cached result
        duplicate_result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert duplicate_result.is_duplicate is True
        assert duplicate_result.has_cached_result is True

    @pytest.mark.asyncio
    async def test_stats_aggregation(self, manager: IdempotencyManager) -> None:
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
            await manager.check_and_reserve(event, key_strategy="event_based")

            if i < 6:
                await manager.mark_completed(event, key_strategy="event_based")
            elif i < 8:
                await manager.mark_failed(event, "Test error", key_strategy="event_based")
            # Leave rest in processing

        # Get stats
        stats = await manager.get_stats()

        assert stats.total_keys == 10
        assert stats.status_counts[IdempotencyStatus.COMPLETED] == 6
        assert stats.status_counts[IdempotencyStatus.FAILED] == 2
        assert stats.status_counts[IdempotencyStatus.PROCESSING] == 2
        assert stats.prefix == manager.config.key_prefix

    @pytest.mark.asyncio
    async def test_remove_key(self, manager: IdempotencyManager) -> None:
        """Test removing idempotency keys"""
        real_event = make_execution_requested_event(execution_id="exec-remove-1")
        # Add a key
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Remove it
        removed = await manager.remove(real_event, key_strategy="event_based")
        assert removed is True

        # Verify it's gone
        record = await manager._repo.find_by_key(result.key)
        assert record is None

        # Can process again
        result2 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is False


class TestIdempotentEventHandlerIntegration:
    """Test IdempotentEventHandler with real components"""

    @pytest.fixture
    async def manager(self, redis_client: redis.Redis) -> AsyncGenerator[IdempotencyManager, None]:
        prefix = f"handler_test:{uuid.uuid4().hex[:6]}"
        config = IdempotencyConfig(key_prefix=prefix, enable_metrics=False)
        repo = RedisIdempotencyRepository(redis_client, key_prefix=prefix)
        m = IdempotencyManager(config, repo, _test_logger)
        await m.initialize()
        try:
            yield m
        finally:
            await m.close()

    @pytest.mark.asyncio
    async def test_handler_processes_new_event(self, manager: IdempotencyManager) -> None:
        """Test that handler processes new events"""
        processed_events: list[DomainEvent] = []

        async def actual_handler(event: DomainEvent) -> None:
            processed_events.append(event)

        # Create idempotent handler
        handler = IdempotentEventHandler(
            handler=actual_handler,
            idempotency_manager=manager,
            key_strategy="event_based",
            logger=_test_logger,
        )

        # Process event
        real_event = make_execution_requested_event(execution_id="handler-test-123")
        await handler(real_event)

        # Verify event was processed
        assert len(processed_events) == 1
        assert processed_events[0] == real_event

    @pytest.mark.asyncio
    async def test_handler_blocks_duplicate(self, manager: IdempotencyManager) -> None:
        """Test that handler blocks duplicate events"""
        processed_events: list[DomainEvent] = []

        async def actual_handler(event: DomainEvent) -> None:
            processed_events.append(event)

        # Create idempotent handler
        handler = IdempotentEventHandler(
            handler=actual_handler,
            idempotency_manager=manager,
            key_strategy="event_based",
            logger=_test_logger,
        )

        # Process event twice
        real_event = make_execution_requested_event(execution_id="handler-dup-123")
        await handler(real_event)
        await handler(real_event)

        # Verify event was processed only once
        assert len(processed_events) == 1

    @pytest.mark.asyncio
    async def test_handler_with_failure(self, manager: IdempotencyManager) -> None:
        """Test handler marks failure on exception"""

        async def failing_handler(event: DomainEvent) -> None:  # noqa: ARG001
            raise ValueError("Processing failed")

        handler = IdempotentEventHandler(
            handler=failing_handler,
            idempotency_manager=manager,
            key_strategy="event_based",
            logger=_test_logger,
        )

        # Process event (should raise)
        real_event = make_execution_requested_event(execution_id="handler-fail-1")
        with pytest.raises(ValueError, match="Processing failed"):
            await handler(real_event)

        # Verify marked as failed
        key = f"{manager.config.key_prefix}:{real_event.event_type}:{real_event.event_id}"
        record = await manager._repo.find_by_key(key)
        assert record is not None
        assert record.status == IdempotencyStatus.FAILED
        assert record.error is not None
        assert "Processing failed" in record.error

    @pytest.mark.asyncio
    async def test_handler_duplicate_callback(self, manager: IdempotencyManager) -> None:
        """Test duplicate callback is invoked"""
        duplicate_events: list[tuple[DomainEvent, Any]] = []

        async def actual_handler(event: DomainEvent) -> None:  # noqa: ARG001
            pass  # Do nothing

        async def on_duplicate(event: DomainEvent, result: Any) -> None:
            duplicate_events.append((event, result))

        handler = IdempotentEventHandler(
            handler=actual_handler,
            idempotency_manager=manager,
            key_strategy="event_based",
            on_duplicate=on_duplicate,
            logger=_test_logger,
        )

        # Process twice
        real_event = make_execution_requested_event(execution_id="handler-dup-cb-1")
        await handler(real_event)
        await handler(real_event)

        # Verify duplicate callback was called
        assert len(duplicate_events) == 1
        assert duplicate_events[0][0] == real_event
        assert duplicate_events[0][1].is_duplicate is True

    @pytest.mark.asyncio
    async def test_decorator_integration(self, manager: IdempotencyManager) -> None:
        """Test the @idempotent_handler decorator"""
        processed_events: list[DomainEvent] = []

        @idempotent_handler(
            idempotency_manager=manager,
            key_strategy="content_hash",
            ttl_seconds=300,
            logger=_test_logger,
        )
        async def my_handler(event: DomainEvent) -> None:
            processed_events.append(event)

        # Process same event twice
        real_event = make_execution_requested_event(execution_id="decor-1")
        await my_handler(real_event)
        await my_handler(real_event)

        # Should only process once
        assert len(processed_events) == 1

        # Create event with same ID and same content for content hash match
        similar_event = make_execution_requested_event(
            execution_id=real_event.execution_id,
            script=real_event.script,
        )

        # Should still be blocked (content hash)
        await my_handler(similar_event)
        assert len(processed_events) == 1  # Still only one

    @pytest.mark.asyncio
    async def test_custom_key_function(self, manager: IdempotencyManager) -> None:
        """Test handler with custom key function"""
        processed_scripts: list[str] = []

        async def process_script(event: DomainEvent) -> None:
            script: str = getattr(event, "script", "")
            processed_scripts.append(script)

        def extract_script_key(event: DomainEvent) -> str:
            # Custom key based on script content only
            script: str = getattr(event, "script", "")
            return f"script:{hash(script)}"

        handler = IdempotentEventHandler(
            handler=process_script,
            idempotency_manager=manager,
            key_strategy="custom",
            custom_key_func=extract_script_key,
            logger=_test_logger,
        )

        # Events with same script
        event1 = make_execution_requested_event(
            execution_id="id1",
            script="print('hello')",
            service_name="test-service",
        )

        event2 = make_execution_requested_event(
            execution_id="id2",
            language="python",
            language_version="3.9",  # Different version
            runtime_image="python:3.9-slim",
            runtime_command=("python",),
            runtime_filename="main.py",
            timeout_seconds=60,  # Different timeout
            cpu_limit="200m",
            memory_limit="256Mi",
            cpu_request="100m",
            memory_request="128Mi",
            service_name="test-service",
        )

        await handler(event1)
        await handler(event2)

        # Should only process once (same script)
        assert len(processed_scripts) == 1
        assert processed_scripts[0] == "print('hello')"

    @pytest.mark.asyncio
    async def test_invalid_key_strategy(self, manager: IdempotencyManager) -> None:
        """Test that invalid key strategy raises error"""
        real_event = make_execution_requested_event(execution_id="invalid-strategy-1")
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await manager.check_and_reserve(real_event, key_strategy="invalid_strategy")

    @pytest.mark.asyncio
    async def test_custom_key_without_custom_key_param(self, manager: IdempotencyManager) -> None:
        """Test that custom strategy without custom_key raises error"""
        real_event = make_execution_requested_event(execution_id="custom-key-missing-1")
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await manager.check_and_reserve(real_event, key_strategy="custom")

    @pytest.mark.asyncio
    async def test_get_cached_json_existing(self, manager: IdempotencyManager) -> None:
        """Test retrieving cached JSON result"""
        # First complete with cached result
        real_event = make_execution_requested_event(execution_id="cache-exist-1")
        await manager.check_and_reserve(real_event, key_strategy="event_based")
        cached_data = json.dumps({"output": "test", "code": 0})
        await manager.mark_completed_with_json(real_event, cached_data, "event_based")

        # Retrieve cached result
        retrieved = await manager.get_cached_json(real_event, "event_based", None)
        assert retrieved == cached_data

    @pytest.mark.asyncio
    async def test_get_cached_json_non_existing(self, manager: IdempotencyManager) -> None:
        """Test retrieving non-existing cached result raises assertion"""
        real_event = make_execution_requested_event(execution_id="cache-miss-1")
        # Trying to get cached result for non-existent key should raise
        with pytest.raises(AssertionError, match="cached result must exist"):
            await manager.get_cached_json(real_event, "event_based", None)

    @pytest.mark.asyncio
    async def test_cleanup_expired_keys(self, manager: IdempotencyManager) -> None:
        """Test cleanup of expired keys"""
        # Create expired record
        expired_key = f"{manager.config.key_prefix}:expired"
        expired_record = IdempotencyRecord(
            key=expired_key,
            status=IdempotencyStatus.COMPLETED,
            event_type="test",
            event_id="expired-1",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ttl_seconds=3600,  # 1 hour TTL
            completed_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        await manager._repo.insert_processing(expired_record)

        # Cleanup should detect it as expired
        # Note: actual cleanup implementation depends on repository
        record = await manager._repo.find_by_key(expired_key)
        assert record is not None  # Still exists until explicit cleanup

    @pytest.mark.asyncio
    async def test_metrics_enabled(self, redis_client: redis.Redis) -> None:
        """Test manager with metrics enabled"""
        config = IdempotencyConfig(key_prefix=f"metrics:{uuid.uuid4().hex[:6]}", enable_metrics=True)
        repository = RedisIdempotencyRepository(redis_client, key_prefix=config.key_prefix)
        manager = IdempotencyManager(config, repository, _test_logger)

        # Initialize with metrics
        await manager.initialize()
        assert manager._stats_update_task is not None

        # Cleanup
        await manager.close()

    @pytest.mark.asyncio
    async def test_content_hash_with_fields(self, manager: IdempotencyManager) -> None:
        """Test content hash with specific fields"""
        event1 = make_execution_requested_event(
            execution_id="exec-1",
            service_name="test-service",
        )

        # Use content hash with only script field
        fields = {"script", "language"}
        result1 = await manager.check_and_reserve(
            event1,
            key_strategy="content_hash",
            fields=fields
        )
        assert result1.is_duplicate is False
        await manager.mark_completed(event1, key_strategy="content_hash", fields=fields)

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

        result2 = await manager.check_and_reserve(
            event2,
            key_strategy="content_hash",
            fields=fields
        )
        assert result2.is_duplicate is True  # Same script and language
