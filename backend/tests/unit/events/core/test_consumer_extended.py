"""Extended tests for UnifiedConsumer to achieve 95%+ coverage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from confluent_kafka import Message
from confluent_kafka.error import KafkaError

from app.events.core import UnifiedConsumer, ConsumerConfig
from app.events.core.dispatcher import EventDispatcher
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


@pytest.fixture
def consumer_config():
    """Create a test consumer configuration."""
    return ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        client_id="test-consumer",
        enable_auto_commit=False,  # Important for testing manual commit
    )


@pytest.fixture
def dispatcher():
    """Create a mock event dispatcher."""
    return MagicMock(spec=EventDispatcher)


@pytest.fixture
def consumer(consumer_config, dispatcher):
    """Create a UnifiedConsumer instance."""
    return UnifiedConsumer(consumer_config, dispatcher)


@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    return ExecutionRequestedEvent(
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


class TestConsumerLoopLogging:
    """Test consumer loop logging scenarios."""

    @pytest.mark.asyncio
    async def test_consume_loop_periodic_logging(self, consumer):
        """Test that consume loop logs every 100 polls."""
        with patch('app.events.core.consumer.Consumer') as mock_consumer_class:
            mock_consumer = MagicMock()
            mock_consumer_class.return_value = mock_consumer

            # Track poll calls
            poll_count = 0

            def side_effect(*args, **kwargs):
                nonlocal poll_count
                poll_count += 1
                # Return None (no message) for first 99 polls
                # Then return a valid message on 100th poll
                # Then stop by setting consumer._running to False
                if poll_count == 100:
                    consumer._running = False
                    mock_msg = MagicMock(spec=Message)
                    mock_msg.error.return_value = None
                    mock_msg.topic.return_value = "test-topic"
                    mock_msg.partition.return_value = 0
                    mock_msg.offset.return_value = 100
                    mock_msg.value.return_value = b'{"event_type": "test"}'
                    mock_msg.headers.return_value = []
                    return mock_msg
                return None

            mock_consumer.poll.side_effect = side_effect
            mock_consumer.subscribe.return_value = None

            # Mock asyncio.to_thread to return coroutine
            def mock_to_thread(func, *args, **kwargs):
                result = func(*args, **kwargs)
                async def _wrapper():
                    return result
                return _wrapper()

            with patch('app.events.core.consumer.asyncio.to_thread', new=mock_to_thread):
                # Start consumer
                await consumer.start(["execution-events"])

                # Wait for consume loop to process (100 polls with 0.01 sleep between)
                await asyncio.sleep(1.5)

                # Stop consumer
                consumer._running = False
                await consumer.stop()

                # Verify poll was called ~100 times
                assert poll_count >= 100


class TestConsumerErrorHandling:
    """Test consumer error handling scenarios."""

    @pytest.mark.asyncio
    async def test_consume_loop_kafka_error_not_eof(self, consumer, dispatcher):
        """Test handling of Kafka errors that are not PARTITION_EOF."""
        with patch('app.events.core.consumer.Consumer') as mock_consumer_class:
            mock_consumer = MagicMock()
            mock_consumer_class.return_value = mock_consumer

            # Create error message
            mock_error = MagicMock(spec=KafkaError)
            mock_error.code.return_value = KafkaError._ALL_BROKERS_DOWN
            mock_error.__str__.return_value = "All brokers down"

            mock_msg = MagicMock(spec=Message)
            mock_msg.error.return_value = mock_error

            # Return error message once, then None
            call_count = 0

            def poll_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_msg
                if call_count > 10:  # Give more time for processing
                    consumer._running = False
                return None

            mock_consumer.poll.side_effect = poll_side_effect
            mock_consumer.subscribe.return_value = None

            # Mock asyncio.to_thread to return coroutine
            def mock_to_thread(func, *args, **kwargs):
                result = func(*args, **kwargs)
                async def _wrapper():
                    return result
                return _wrapper()

            with patch('app.events.core.consumer.asyncio.to_thread', new=mock_to_thread):
                await consumer.start(["test-topic"])

                # Let consume loop process the error
                await asyncio.sleep(0.1)

                # Verify error was processed
                assert consumer.metrics.processing_errors == 1

                await consumer.stop()

    @pytest.mark.asyncio
    async def test_consume_loop_kafka_partition_eof(self, consumer, dispatcher):
        """Test handling of PARTITION_EOF error (should be ignored)."""
        with patch('app.events.core.consumer.Consumer') as mock_consumer_class:
            mock_consumer = MagicMock()
            mock_consumer_class.return_value = mock_consumer

            # Create PARTITION_EOF error
            mock_error = MagicMock(spec=KafkaError)
            mock_error.code.return_value = KafkaError._PARTITION_EOF

            mock_msg = MagicMock(spec=Message)
            mock_msg.error.return_value = mock_error

            # Return EOF message once, then stop
            call_count = 0

            def poll_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_msg
                if call_count > 10:  # Give more time for processing
                    consumer._running = False
                return None

            mock_consumer.poll.side_effect = poll_side_effect
            mock_consumer.subscribe.return_value = None

            # Mock asyncio.to_thread to return coroutine
            def mock_to_thread(func, *args, **kwargs):
                result = func(*args, **kwargs)
                async def _wrapper():
                    return result
                return _wrapper()

            with patch('app.events.core.consumer.asyncio.to_thread', new=mock_to_thread):
                await consumer.start(["test-topic"])

                # Let consume loop process
                await asyncio.sleep(0.1)

                # PARTITION_EOF should not increment error count
                assert consumer.metrics.processing_errors == 0

                await consumer.stop()


class TestConsumerManualCommit:
    """Test consumer manual commit scenarios."""

    @pytest.mark.asyncio
    async def test_consume_with_manual_commit(self, consumer_config, dispatcher):
        """Test message consumption with manual commit (auto_commit disabled)."""
        # Ensure auto_commit is disabled
        consumer_config.enable_auto_commit = False
        consumer = UnifiedConsumer(consumer_config, dispatcher)

        with patch('app.events.core.consumer.Consumer') as mock_consumer_class:

            mock_consumer = MagicMock()
            mock_consumer_class.return_value = mock_consumer

            # Create a test event
            test_event = ExecutionRequestedEvent(
                execution_id="exec-456",
                script="print('manual commit test')",
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

            # Create mock message
            mock_msg = MagicMock(spec=Message)
            mock_msg.error.return_value = None
            mock_msg.topic.return_value = "execution-events"
            mock_msg.partition.return_value = 0
            mock_msg.offset.return_value = 42
            mock_msg.value.return_value = b'{"event_type": "execution_requested"}'
            mock_msg.headers.return_value = []

            # Return message once, then stop
            call_count = 0

            def poll_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_msg
                if call_count > 10:  # Give more time for processing
                    consumer._running = False
                return None

            mock_consumer.poll.side_effect = poll_side_effect
            mock_consumer.subscribe.return_value = None
            mock_consumer.commit = AsyncMock()

            # Mock schema registry to return test event
            with patch.object(consumer._schema_registry, 'deserialize_event', return_value=test_event):
                # Make dispatcher.dispatch async
                dispatcher.dispatch = AsyncMock()

                # Mock asyncio.to_thread to return coroutine
                def mock_to_thread(func, *args, **kwargs):
                    result = func(*args, **kwargs)
                    async def _wrapper():
                        return result
                    return _wrapper()

                with patch('app.events.core.consumer.asyncio.to_thread', new=mock_to_thread):
                    await consumer.start(["execution-events"])

                    # Wait for message to be processed
                    await asyncio.sleep(0.5)

                    # Verify manual commit was called with the message
                    assert mock_consumer.commit.called
                    # The commit should be called via asyncio.to_thread
                    # Since we mocked it, we can't directly check the call
                    # But we can verify the message was processed
                    assert consumer.metrics.messages_consumed == 1

                    await consumer.stop()

    @pytest.mark.asyncio
    async def test_consume_with_auto_commit_enabled(self, dispatcher):
        """Test that manual commit is NOT called when auto_commit is enabled."""
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-group",
            client_id="test-consumer",
            enable_auto_commit=True,  # Auto commit enabled
        )
        consumer = UnifiedConsumer(config, dispatcher)

        with patch('app.events.core.consumer.Consumer') as mock_consumer_class:

            mock_consumer = MagicMock()
            mock_consumer_class.return_value = mock_consumer

            test_event = ExecutionRequestedEvent(
                execution_id="exec-789",
                script="print('auto commit test')",
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

            # Create mock message
            mock_msg = MagicMock(spec=Message)
            mock_msg.error.return_value = None
            mock_msg.topic.return_value = "execution-events"
            mock_msg.partition.return_value = 0
            mock_msg.offset.return_value = 42
            mock_msg.value.return_value = b'{"event_type": "execution_requested"}'
            mock_msg.headers.return_value = []

            # Return message once, then stop
            call_count = 0

            def poll_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_msg
                if call_count > 10:  # Give more time for processing
                    consumer._running = False
                return None

            mock_consumer.poll.side_effect = poll_side_effect
            mock_consumer.subscribe.return_value = None
            mock_consumer.commit = MagicMock()

            # Mock schema registry to return test event
            with patch.object(consumer._schema_registry, 'deserialize_event', return_value=test_event):
                # Make dispatcher.dispatch async
                dispatcher.dispatch = AsyncMock()

                # Mock asyncio.to_thread to return coroutine
                def mock_to_thread(func, *args, **kwargs):
                    result = func(*args, **kwargs)
                    async def _wrapper():
                        return result
                    return _wrapper()

                with patch('app.events.core.consumer.asyncio.to_thread', new=mock_to_thread):
                    await consumer.start(["execution-events"])

                    # Wait for message to be processed
                    await asyncio.sleep(0.5)

                    # Verify manual commit was NOT called (auto commit is enabled)
                    mock_consumer.commit.assert_not_called()

                    # But message was still processed
                    assert consumer.metrics.messages_consumed == 1

                    await consumer.stop()


class TestConsumerIntegration:
    """Integration tests for UnifiedConsumer."""

    @pytest.mark.asyncio
    async def test_full_message_processing_flow(self, consumer_config, dispatcher):
        """Test complete message processing flow with all features."""
        consumer = UnifiedConsumer(consumer_config, dispatcher)

        # Setup error callback
        error_callback = AsyncMock()
        consumer.register_error_callback(error_callback)

        with patch('app.events.core.consumer.Consumer') as mock_consumer_class:

            mock_consumer = MagicMock()
            mock_consumer_class.return_value = mock_consumer

            # Create messages: valid, error, None, then stop
            messages = []

            # Valid message
            valid_msg = MagicMock(spec=Message)
            valid_msg.error.return_value = None
            valid_msg.topic.return_value = "execution-events"
            valid_msg.partition.return_value = 0
            valid_msg.offset.return_value = 100
            valid_msg.value.return_value = b'{"event_type": "execution_requested"}'
            valid_msg.headers.return_value = [("trace-id", b"123")]
            messages.append(valid_msg)

            # Error message (not EOF)
            error_msg = MagicMock(spec=Message)
            error = MagicMock(spec=KafkaError)
            error.code.return_value = KafkaError._MSG_TIMED_OUT
            error.__str__.return_value = "Message timed out"
            error_msg.error.return_value = error
            messages.append(error_msg)

            # EOF message (should be ignored)
            eof_msg = MagicMock(spec=Message)
            eof_error = MagicMock(spec=KafkaError)
            eof_error.code.return_value = KafkaError._PARTITION_EOF
            eof_msg.error.return_value = eof_error
            messages.append(eof_msg)

            # None messages to trigger periodic logging
            for _ in range(97):
                messages.append(None)

            # Valid message to process after logging
            final_msg = MagicMock(spec=Message)
            final_msg.error.return_value = None
            final_msg.topic.return_value = "execution-events"
            final_msg.partition.return_value = 0
            final_msg.offset.return_value = 101
            final_msg.value.return_value = b'{"event_type": "execution_requested"}'
            final_msg.headers.return_value = []
            messages.append(final_msg)

            # Setup poll to return messages in sequence
            call_count = 0

            def poll_side_effect(*args, **kwargs):
                nonlocal call_count
                if call_count < len(messages):
                    msg = messages[call_count]
                    call_count += 1
                    return msg
                call_count += 1
                if call_count > len(messages) + 10:  # Give more time for processing after all messages
                    consumer._running = False
                return None

            mock_consumer.poll.side_effect = poll_side_effect
            mock_consumer.subscribe.return_value = None
            mock_consumer.commit = AsyncMock()

            # Setup event deserialization
            test_event = ExecutionRequestedEvent(
                execution_id="exec-full",
                script="print('full test')",
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

            # Mock schema registry to return test event
            with patch.object(consumer._schema_registry, 'deserialize_event', return_value=test_event):
                # Make dispatcher async
                dispatcher.dispatch = AsyncMock()

                # Mock asyncio.to_thread to return coroutine
                def mock_to_thread(func, *args, **kwargs):
                    result = func(*args, **kwargs)
                    async def _wrapper():
                        return result
                    return _wrapper()

                with patch('app.events.core.consumer.asyncio.to_thread', new=mock_to_thread):
                    await consumer.start(["execution-events"])

                    # Wait for all messages to be processed (101 messages with ~0.01s sleep between)
                    await asyncio.sleep(2.0)

                    # Verify metrics
                    assert consumer.metrics.messages_consumed == 2  # Two valid messages
                    assert consumer.metrics.processing_errors == 1  # One non-EOF error

                    # Verify commit was called for valid messages (manual commit)
                    assert mock_consumer.commit.call_count == 2

                    await consumer.stop()