"""Extended tests for EventStoreConsumer to achieve 95%+ coverage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.events.event_store_consumer import EventStoreConsumer
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


def make_test_event(event_id: str = "test-event-1") -> ExecutionRequestedEvent:
    """Create a test event."""
    return ExecutionRequestedEvent(
        event_id=event_id,
        execution_id="exec-123",
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
        priority=5,
        metadata=EventMetadata(service_name="test", service_version="1.0.0"),
    )


class TestEventStoreConsumerBatchTimeout:
    """Test batch timeout scenarios."""

    @pytest.mark.asyncio
    async def test_batch_processor_timeout_flush(self):
        """Test that batch processor flushes on timeout."""
        mock_event_store = AsyncMock()
        mock_event_store.store_batch.return_value = {
            'total': 1, 'stored': 1, 'duplicates': 0, 'failed': 0
        }
        mock_producer = AsyncMock()

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=10,  # High batch size so it won't trigger size flush
            batch_timeout_seconds=0.1,  # 100ms timeout
        )

        # Mock the UnifiedConsumer to avoid real Kafka connection
        with patch.object(consumer, 'consumer'):
            consumer.consumer = AsyncMock()
            consumer.consumer.start = AsyncMock()
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Add a single event to the buffer (not enough to trigger size flush)
            event = make_test_event("timeout-event")
            await consumer._handle_event(event)

            # Verify event is in buffer but not yet flushed
            assert len(consumer._batch_buffer) == 1
            assert mock_event_store.store_batch.call_count == 0

            # Wait for batch processor to check timeout (it sleeps for 1 second first)
            await asyncio.sleep(1.2)

            # The batch processor should have flushed due to timeout
            assert mock_event_store.store_batch.call_count >= 1

            # Stop the consumer
            consumer._running = False
            if consumer._batch_task:
                consumer._batch_task.cancel()
                try:
                    await consumer._batch_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_batch_processor_timeout_with_multiple_events(self):
        """Test batch timeout with multiple events but below batch size."""
        mock_event_store = AsyncMock()
        mock_event_store.store_batch.return_value = {
            'total': 5, 'stored': 5, 'duplicates': 0, 'failed': 0
        }
        mock_producer = AsyncMock()

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=20,  # High batch size
            batch_timeout_seconds=0.1,  # 100ms timeout
        )

        # Mock the UnifiedConsumer to avoid real Kafka connection
        with patch.object(consumer, 'consumer'):
            consumer.consumer = AsyncMock()
            consumer.consumer.start = AsyncMock()
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Add multiple events but less than batch_size
            for i in range(5):
                event = make_test_event(f"timeout-event-{i}")
                await consumer._handle_event(event)

            # Verify events are buffered
            assert len(consumer._batch_buffer) == 5
            assert mock_event_store.store_batch.call_count == 0

            # Wait for batch processor to check timeout (it sleeps for 1 second first)
            await asyncio.sleep(1.2)

            # Should have flushed due to timeout
            assert mock_event_store.store_batch.call_count >= 1

            # The buffer should be empty after flush
            await asyncio.sleep(0.1)  # Give time for flush to complete
            assert len(consumer._batch_buffer) == 0

            await consumer.stop()

    @pytest.mark.asyncio
    async def test_batch_processor_exception_handling(self):
        """Test exception handling in batch processor."""
        mock_event_store = AsyncMock()
        mock_producer = AsyncMock()

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=10,
            batch_timeout_seconds=0.1,
        )

        # Mock asyncio.get_event_loop().time() to raise an exception
        with patch('asyncio.get_event_loop') as mock_loop:
            mock_loop_instance = MagicMock()
            mock_loop.return_value = mock_loop_instance

            # First call works normally
            mock_loop_instance.time.side_effect = [
                100.0,  # Initial time
                Exception("Test exception in batch processor"),  # Exception on second call
                200.0,  # Subsequent calls work
                201.0,
            ]

            # Start the consumer
            # Mock the UnifiedConsumer to avoid real Kafka connection
            consumer.consumer = AsyncMock()
            consumer.consumer.start = AsyncMock()
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Add an event
            event = make_test_event("exception-test")
            await consumer._handle_event(event)

            # Wait for batch processor to run and handle exception
            await asyncio.sleep(0.2)

            # Consumer should still be running despite exception
            assert consumer._batch_task is not None
            assert not consumer._batch_task.done()

            await consumer.stop()

    @pytest.mark.asyncio
    async def test_batch_timeout_edge_cases(self):
        """Test edge cases in batch timeout logic."""
        mock_event_store = AsyncMock()
        mock_event_store.store_batch.return_value = {
            'total': 2, 'stored': 2, 'duplicates': 0, 'failed': 0
        }
        mock_producer = AsyncMock()

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=5,
            batch_timeout_seconds=0.05,  # 50ms timeout
        )

        # Mock the start method to avoid real Kafka connection
        with patch.object(consumer, 'consumer', new=AsyncMock()):
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Scenario 1: Add event, wait partial timeout, add more, wait for full timeout
            event1 = make_test_event("edge-1")
            await consumer._handle_event(event1)

            # Wait less than timeout
            await asyncio.sleep(0.02)

            # Add another event (resets timer)
            event2 = make_test_event("edge-2")
            await consumer._handle_event(event2)

            # Buffer should have 2 events
            assert len(consumer._batch_buffer) == 2

            # Wait for batch processor to check timeout (it sleeps for 1 second first)
            await asyncio.sleep(1.2)

            # Should have flushed
            assert mock_event_store.store_batch.call_count >= 1

            await consumer.stop()

    @pytest.mark.asyncio
    async def test_batch_processor_concurrent_flush(self):
        """Test concurrent access to batch buffer during timeout flush."""
        mock_event_store = AsyncMock()
        mock_producer = AsyncMock()

        # Add delay to store_batch to simulate slow operation
        async def slow_store_batch(events):
            await asyncio.sleep(0.05)
            return {'total': len(events), 'stored': len(events), 'duplicates': 0, 'failed': 0}

        mock_event_store.store_batch = slow_store_batch

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=10,
            batch_timeout_seconds=0.1,
        )

        # Mock the start method to avoid real Kafka connection
        with patch.object(consumer, 'consumer', new=AsyncMock()):
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Add initial events
            for i in range(3):
                event = make_test_event(f"concurrent-{i}")
                await consumer._handle_event(event)

            # Wait for batch processor to check timeout (it sleeps for 1 second first)
            await asyncio.sleep(1.2)

            # Try to add more events while flush might be happening
            for i in range(3, 6):
                event = make_test_event(f"concurrent-{i}")
                await consumer._handle_event(event)

            # Wait for all operations to complete
            await asyncio.sleep(0.2)

            # Stop and verify final state
            await consumer.stop()

            # All events should have been processed
            # The exact number of batches depends on timing
            assert len(consumer._batch_buffer) < 6


class TestEventStoreConsumerAdvanced:
    """Advanced test scenarios for EventStoreConsumer."""

    @pytest.mark.asyncio
    async def test_rapid_event_handling(self):
        """Test handling many events rapidly."""
        mock_event_store = AsyncMock()
        mock_event_store.store_batch.return_value = {
            'total': 5, 'stored': 5, 'duplicates': 0, 'failed': 0
        }
        mock_producer = AsyncMock()

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=5,
            batch_timeout_seconds=0.5,
        )

        # Mock the start method to avoid real Kafka connection
        with patch.object(consumer, 'consumer', new=AsyncMock()):
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Rapidly add many events
            events = []
            for i in range(20):
                event = make_test_event(f"rapid-{i}")
                events.append(event)
                await consumer._handle_event(event)
                # Small delay between events
                await asyncio.sleep(0.001)

            # Should have triggered multiple batch flushes due to size
            # 20 events / batch_size of 5 = 4 flushes
            assert mock_event_store.store_batch.call_count >= 4

            await consumer.stop()

    @pytest.mark.asyncio
    async def test_stop_with_pending_timeout_flush(self):
        """Test stopping consumer with events waiting for timeout flush."""
        mock_event_store = AsyncMock()
        mock_event_store.store_batch.return_value = {
            'total': 3, 'stored': 3, 'duplicates': 0, 'failed': 0
        }
        mock_producer = AsyncMock()

        consumer = EventStoreConsumer(
            event_store=mock_event_store,
            topics=[],  # Required parameter
            schema_registry_manager=MagicMock(),  # Required parameter
            producer=mock_producer,
            batch_size=10,
            batch_timeout_seconds=1.0,  # Long timeout
        )

        # Mock the start method to avoid real Kafka connection
        with patch.object(consumer, 'consumer', new=AsyncMock()):
            consumer._running = True
            consumer._batch_task = asyncio.create_task(consumer._batch_processor())

            # Add events that won't trigger size flush
            for i in range(3):
                event = make_test_event(f"pending-{i}")
                await consumer._handle_event(event)

            # Events should be buffered
            assert len(consumer._batch_buffer) == 3

            # Stop immediately (before timeout)
            await consumer.stop()

            # Stop should have flushed remaining events
            assert mock_event_store.store_batch.call_count == 1
            # Buffer should be empty
            assert len(consumer._batch_buffer) == 0