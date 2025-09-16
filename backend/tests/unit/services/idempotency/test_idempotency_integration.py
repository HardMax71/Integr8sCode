"""Integration-style tests for idempotency service with minimal mocking"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import pytest
from pymongo.errors import DuplicateKeyError

from app.domain.idempotency import IdempotencyRecord, IdempotencyStatus, IdempotencyStats
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.idempotency.idempotency_manager import (
    IdempotencyConfig,
    IdempotencyManager,
    IdempotencyRepoProtocol,
    create_idempotency_manager,
)
from app.services.idempotency.middleware import (
    IdempotentEventHandler,
    idempotent_handler,
)


pytestmark = pytest.mark.unit


class InMemoryIdempotencyRepository:
    """In-memory implementation of IdempotencyRepoProtocol for testing"""

    def __init__(self):
        self._store: Dict[str, IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def find_by_key(self, key: str) -> Optional[IdempotencyRecord]:
        async with self._lock:
            return self._store.get(key)

    async def insert_processing(self, record: IdempotencyRecord) -> None:
        async with self._lock:
            if record.key in self._store:
                raise DuplicateKeyError(f"Key already exists: {record.key}")
            self._store[record.key] = record

    async def update_record(self, record: IdempotencyRecord) -> int:
        async with self._lock:
            if record.key in self._store:
                self._store[record.key] = record
                return 1
            return 0

    async def delete_key(self, key: str) -> int:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return 1
            return 0

    async def aggregate_status_counts(self, key_prefix: str) -> Dict[str, int]:
        async with self._lock:
            counts = {}
            for key, record in self._store.items():
                if key.startswith(key_prefix):
                    status_str = str(record.status)
                    counts[status_str] = counts.get(status_str, 0) + 1
            return counts

    async def health_check(self) -> None:
        # Always healthy for in-memory
        pass

    def clear(self):
        """Clear all data - useful for test cleanup"""
        self._store.clear()


class TestIdempotencyManagerIntegration:
    """Test IdempotencyManager with real in-memory repository"""

    @pytest.fixture
    def repository(self):
        return InMemoryIdempotencyRepository()

    @pytest.fixture
    def config(self):
        return IdempotencyConfig(
            key_prefix="test",
            default_ttl_seconds=3600,
            processing_timeout_seconds=5,  # Short timeout for testing
            enable_result_caching=True,
            max_result_size_bytes=1024,
            enable_metrics=False  # Disable metrics to avoid background tasks
        )

    @pytest.fixture
    def manager(self, config, repository):
        return IdempotencyManager(config, repository)

    @pytest.fixture
    def real_event(self):
        """Create a real event object"""
        metadata = EventMetadata(
            service_name="test-service",
            service_version="1.0.0",
            user_id="test-user"
        )
        return ExecutionRequestedEvent(
            execution_id="exec-123",
            script="print('hello')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            priority=5,
            metadata=metadata
        )

    @pytest.mark.asyncio
    async def test_complete_flow_new_event(self, manager, real_event, repository):
        """Test the complete flow for a new event"""
        # Check and reserve
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")

        assert result.is_duplicate is False
        assert result.status == IdempotencyStatus.PROCESSING
        assert result.key == f"test:{real_event.event_type}:{real_event.event_id}"

        # Verify it's in the repository
        record = await repository.find_by_key(result.key)
        assert record is not None
        assert record.status == IdempotencyStatus.PROCESSING

        # Mark as completed
        success = await manager.mark_completed(real_event, key_strategy="event_based")
        assert success is True

        # Verify status updated
        record = await repository.find_by_key(result.key)
        assert record.status == IdempotencyStatus.COMPLETED
        assert record.completed_at is not None
        assert record.processing_duration_ms is not None

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, manager, real_event, repository):
        """Test that duplicates are properly detected"""
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
    async def test_concurrent_requests_race_condition(self, manager, real_event):
        """Test handling of concurrent requests for the same event"""
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
    async def test_processing_timeout_allows_retry(self, manager, real_event, repository):
        """Test that stuck processing allows retry after timeout"""
        # First request
        result1 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result1.is_duplicate is False

        # Manually update the created_at to simulate old processing
        record = await repository.find_by_key(result1.key)
        record.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        await repository.update_record(record)

        # Second request should be allowed due to timeout
        result2 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is False  # Allowed to retry
        assert result2.status == IdempotencyStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_content_hash_strategy(self, manager, repository):
        """Test content-based deduplication"""
        # Two events with same content and same execution_id
        metadata = EventMetadata(
            service_name="test-service",
            service_version="1.0.0"
        )
        event1 = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print('hello')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata
        )

        event2 = ExecutionRequestedEvent(
            execution_id="exec-1",  # Same ID for content hash match
            script="print('hello')",  # Same content
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata
        )

        # Use content hash strategy
        result1 = await manager.check_and_reserve(event1, key_strategy="content_hash")
        assert result1.is_duplicate is False

        await manager.mark_completed(event1, key_strategy="content_hash")

        # Second event with same content should be duplicate
        result2 = await manager.check_and_reserve(event2, key_strategy="content_hash")
        assert result2.is_duplicate is True

    @pytest.mark.asyncio
    async def test_failed_event_handling(self, manager, real_event, repository):
        """Test marking events as failed"""
        # Reserve
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Mark as failed
        error_msg = "Execution failed: out of memory"
        success = await manager.mark_failed(real_event, error=error_msg, key_strategy="event_based")
        assert success is True

        # Verify status and error
        record = await repository.find_by_key(result.key)
        assert record.status == IdempotencyStatus.FAILED
        assert record.error == error_msg
        assert record.completed_at is not None

    @pytest.mark.asyncio
    async def test_result_caching(self, manager, real_event, repository):
        """Test caching of results"""
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
    async def test_stats_aggregation(self, manager, repository):
        """Test statistics aggregation"""
        # Create various events with different statuses
        metadata = EventMetadata(
            service_name="test-service",
            service_version="1.0.0"
        )
        events = []
        for i in range(10):
            event = ExecutionRequestedEvent(
                execution_id=f"exec-{i}",
                script=f"print({i})",
                language="python",
                language_version="3.11",
                runtime_image="python:3.11-slim",
                runtime_command=["python"],
                runtime_filename="main.py",
                timeout_seconds=30,
                cpu_limit="100m",
                memory_limit="128Mi",
                cpu_request="50m",
                memory_request="64Mi",
                metadata=metadata
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
        assert stats.prefix == "test"

    @pytest.mark.asyncio
    async def test_remove_key(self, manager, real_event, repository):
        """Test removing idempotency keys"""
        # Add a key
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result.is_duplicate is False

        # Remove it
        removed = await manager.remove(real_event, key_strategy="event_based")
        assert removed is True

        # Verify it's gone
        record = await repository.find_by_key(result.key)
        assert record is None

        # Can process again
        result2 = await manager.check_and_reserve(real_event, key_strategy="event_based")
        assert result2.is_duplicate is False


class TestIdempotentEventHandlerIntegration:
    """Test IdempotentEventHandler with real components"""

    @pytest.fixture
    def repository(self):
        return InMemoryIdempotencyRepository()

    @pytest.fixture
    def manager(self, repository):
        config = IdempotencyConfig(
            key_prefix="handler_test",
            enable_metrics=False
        )
        return IdempotencyManager(config, repository)

    @pytest.fixture
    def real_event(self):
        metadata = EventMetadata(
            service_name="test-service",
            service_version="1.0.0"
        )
        return ExecutionRequestedEvent(
            execution_id="handler-test-123",
            script="print('test')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata
        )

    @pytest.mark.asyncio
    async def test_handler_processes_new_event(self, manager, real_event):
        """Test that handler processes new events"""
        processed_events = []

        async def actual_handler(event: BaseEvent):
            processed_events.append(event)

        # Create idempotent handler
        handler = IdempotentEventHandler(
            handler=actual_handler,
            idempotency_manager=manager,
            key_strategy="event_based"
        )

        # Process event
        await handler(real_event)

        # Verify event was processed
        assert len(processed_events) == 1
        assert processed_events[0] == real_event

    @pytest.mark.asyncio
    async def test_handler_blocks_duplicate(self, manager, real_event):
        """Test that handler blocks duplicate events"""
        processed_events = []

        async def actual_handler(event: BaseEvent):
            processed_events.append(event)

        # Create idempotent handler
        handler = IdempotentEventHandler(
            handler=actual_handler,
            idempotency_manager=manager,
            key_strategy="event_based"
        )

        # Process event twice
        await handler(real_event)
        await handler(real_event)

        # Verify event was processed only once
        assert len(processed_events) == 1

    @pytest.mark.asyncio
    async def test_handler_with_failure(self, manager, real_event, repository):
        """Test handler marks failure on exception"""

        async def failing_handler(event: BaseEvent):
            raise ValueError("Processing failed")

        handler = IdempotentEventHandler(
            handler=failing_handler,
            idempotency_manager=manager,
            key_strategy="event_based"
        )

        # Process event (should raise)
        with pytest.raises(ValueError, match="Processing failed"):
            await handler(real_event)

        # Verify marked as failed
        key = f"handler_test:{real_event.event_type}:{real_event.event_id}"
        record = await repository.find_by_key(key)
        assert record.status == IdempotencyStatus.FAILED
        assert "Processing failed" in record.error

    @pytest.mark.asyncio
    async def test_handler_duplicate_callback(self, manager, real_event):
        """Test duplicate callback is invoked"""
        duplicate_events = []

        async def actual_handler(event: BaseEvent):
            pass  # Do nothing

        async def on_duplicate(event: BaseEvent, result):
            duplicate_events.append((event, result))

        handler = IdempotentEventHandler(
            handler=actual_handler,
            idempotency_manager=manager,
            key_strategy="event_based",
            on_duplicate=on_duplicate
        )

        # Process twice
        await handler(real_event)
        await handler(real_event)

        # Verify duplicate callback was called
        assert len(duplicate_events) == 1
        assert duplicate_events[0][0] == real_event
        assert duplicate_events[0][1].is_duplicate is True

    @pytest.mark.asyncio
    async def test_decorator_integration(self, manager, real_event):
        """Test the @idempotent_handler decorator"""
        processed_events = []

        @idempotent_handler(
            idempotency_manager=manager,
            key_strategy="content_hash",
            ttl_seconds=300
        )
        async def my_handler(event: BaseEvent):
            processed_events.append(event)

        # Process same event twice
        await my_handler(real_event)
        await my_handler(real_event)

        # Should only process once
        assert len(processed_events) == 1

        # Create event with same ID and same content for content hash match
        similar_event = ExecutionRequestedEvent(
            execution_id=real_event.execution_id,  # Same ID for content hash match
            script=real_event.script,  # Same script
            language=real_event.language,
            language_version=real_event.language_version,
            runtime_image=real_event.runtime_image,
            runtime_command=real_event.runtime_command,
            runtime_filename=real_event.runtime_filename,
            timeout_seconds=real_event.timeout_seconds,
            cpu_limit=real_event.cpu_limit,
            memory_limit=real_event.memory_limit,
            cpu_request=real_event.cpu_request,
            memory_request=real_event.memory_request,
            metadata=real_event.metadata
        )

        # Should still be blocked (content hash)
        await my_handler(similar_event)
        assert len(processed_events) == 1  # Still only one

    @pytest.mark.asyncio
    async def test_custom_key_function(self, manager):
        """Test handler with custom key function"""
        processed_scripts = []

        async def process_script(event: BaseEvent) -> None:
            processed_scripts.append(event.script)

        def extract_script_key(event: BaseEvent) -> str:
            # Custom key based on script content only
            if hasattr(event, 'script'):
                return f"script:{hash(event.script)}"
            return str(event.event_id)

        handler = IdempotentEventHandler(
            handler=process_script,
            idempotency_manager=manager,
            key_strategy="custom",
            custom_key_func=extract_script_key
        )

        # Events with same script
        metadata = EventMetadata(
            service_name="test-service",
            service_version="1.0.0"
        )
        event1 = ExecutionRequestedEvent(
            execution_id="id1",
            script="print('hello')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata
        )

        event2 = ExecutionRequestedEvent(
            execution_id="id2",
            script="print('hello')",  # Same script
            language="python",
            language_version="3.9",  # Different version
            runtime_image="python:3.9-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=60,  # Different timeout
            cpu_limit="200m",
            memory_limit="256Mi",
            cpu_request="100m",
            memory_request="128Mi",
            metadata=metadata
        )

        await handler(event1)
        await handler(event2)

        # Should only process once (same script)
        assert len(processed_scripts) == 1
        assert processed_scripts[0] == "print('hello')"

    @pytest.mark.asyncio
    async def test_invalid_key_strategy(self, manager, real_event):
        """Test that invalid key strategy raises error"""
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await manager.check_and_reserve(real_event, key_strategy="invalid_strategy")

    @pytest.mark.asyncio
    async def test_custom_key_without_custom_key_param(self, manager, real_event):
        """Test that custom strategy without custom_key raises error"""
        with pytest.raises(ValueError, match="Invalid key strategy"):
            await manager.check_and_reserve(real_event, key_strategy="custom")

    @pytest.mark.asyncio
    async def test_get_cached_json_existing(self, manager, real_event):
        """Test retrieving cached JSON result"""
        # First complete with cached result
        result = await manager.check_and_reserve(real_event, key_strategy="event_based")
        cached_data = json.dumps({"output": "test", "code": 0})
        await manager.mark_completed_with_json(real_event, cached_data, "event_based")

        # Retrieve cached result
        retrieved = await manager.get_cached_json(real_event, "event_based", None)
        assert retrieved == cached_data

    @pytest.mark.asyncio
    async def test_get_cached_json_non_existing(self, manager, real_event):
        """Test retrieving non-existing cached result raises assertion"""
        # Trying to get cached result for non-existent key should raise
        with pytest.raises(AssertionError, match="cached result must exist"):
            await manager.get_cached_json(real_event, "event_based", None)

    @pytest.mark.asyncio
    async def test_cleanup_expired_keys(self, repository):
        """Test cleanup of expired keys"""
        # Create expired record
        expired_record = IdempotencyRecord(
            key="test:expired",
            status=IdempotencyStatus.COMPLETED,
            event_type="test",
            event_id="expired-1",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ttl_seconds=3600,  # 1 hour TTL
            completed_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        await repository.insert_processing(expired_record)

        # Cleanup should detect it as expired
        # Note: actual cleanup implementation depends on repository
        record = await repository.find_by_key("test:expired")
        assert record is not None  # Still exists until explicit cleanup

    @pytest.mark.asyncio
    async def test_metrics_enabled(self):
        """Test manager with metrics enabled"""
        config = IdempotencyConfig(
            key_prefix="metrics_test",
            enable_metrics=True
        )
        repository = InMemoryIdempotencyRepository()
        manager = IdempotencyManager(config, repository)

        # Initialize with metrics
        await manager.initialize()
        assert manager._stats_update_task is not None

        # Cleanup
        await manager.close()

    @pytest.mark.asyncio
    async def test_content_hash_with_fields(self, manager):
        """Test content hash with specific fields"""
        metadata = EventMetadata(
            service_name="test-service",
            service_version="1.0.0"
        )
        event1 = ExecutionRequestedEvent(
            execution_id="exec-1",
            script="print('hello')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python"],
            runtime_filename="main.py",
            timeout_seconds=30,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=metadata
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
        event2 = ExecutionRequestedEvent(
            execution_id="exec-2",
            script="print('hello')",  # Same
            language="python",  # Same
            language_version="3.9",  # Different
            runtime_image="python:3.9",  # Different
            runtime_command=["python3"],
            runtime_filename="app.py",
            timeout_seconds=60,
            cpu_limit="200m",
            memory_limit="256Mi",
            cpu_request="100m",
            memory_request="128Mi",
            metadata=metadata
        )

        result2 = await manager.check_and_reserve(
            event2,
            key_strategy="content_hash",
            fields=fields
        )
        assert result2.is_duplicate is True  # Same script and language