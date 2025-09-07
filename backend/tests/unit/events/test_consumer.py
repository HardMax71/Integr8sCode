"""Tests for app/events/core/consumer.py - covering missing lines"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, MagicMock, patch, call
import pytest

from confluent_kafka import Consumer, Message, TopicPartition, OFFSET_BEGINNING, OFFSET_END
from confluent_kafka.error import KafkaError

from app.events.core.consumer import UnifiedConsumer
from app.events.core.types import ConsumerConfig, ConsumerState, ConsumerMetrics
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.base import BaseEvent


@pytest.fixture
def consumer_config():
    """Create ConsumerConfig"""
    config = Mock(spec=ConsumerConfig)
    config.group_id = "test-group"
    config.client_id = "test-client"
    config.enable_auto_commit = True
    config.to_consumer_config.return_value = {
        "bootstrap.servers": "localhost:9092",
        "group.id": "test-group",
        "client.id": "test-client"
    }
    return config


@pytest.fixture
def mock_schema_registry():
    """Mock SchemaRegistryManager"""
    registry = Mock()
    event = Mock(spec=BaseEvent)
    event.event_id = "event_123"
    event.event_type = "execution_requested"
    registry.deserialize_event = Mock(return_value=event)
    return registry


@pytest.fixture
def mock_dispatcher():
    """Mock EventDispatcher"""
    dispatcher = AsyncMock()
    dispatcher.dispatch = AsyncMock()
    return dispatcher


@pytest.fixture
def mock_event_metrics():
    """Mock event metrics"""
    metrics = Mock()
    metrics.record_kafka_message_consumed = Mock()
    metrics.record_kafka_consumption_error = Mock()
    return metrics


@pytest.fixture
def consumer(consumer_config, mock_schema_registry, mock_dispatcher, mock_event_metrics):
    """Create UnifiedConsumer with mocked dependencies"""
    with patch('app.events.core.consumer.get_event_metrics', return_value=mock_event_metrics):
        uc = UnifiedConsumer(
            config=consumer_config,
            event_dispatcher=mock_dispatcher,
            stats_callback=None
        )
        # Inject mocked schema registry
        uc._schema_registry = mock_schema_registry  # type: ignore[attr-defined]
        return uc


@pytest.mark.asyncio
async def test_start_with_stats_callback(consumer_config, mock_schema_registry, mock_dispatcher, mock_event_metrics):
    """Test start with stats callback configured"""
    stats_callback = Mock()
    
    with patch('app.events.core.consumer.get_event_metrics', return_value=mock_event_metrics):
        consumer = UnifiedConsumer(
            config=consumer_config,
            event_dispatcher=mock_dispatcher,
            stats_callback=stats_callback
        )
    
    with patch('app.events.core.consumer.Consumer') as mock_consumer_class:
        mock_consumer_instance = Mock()
        mock_consumer_class.return_value = mock_consumer_instance
        
        await consumer.start([KafkaTopic.EXECUTION_EVENTS])
        
        # Check that stats_cb was set in config
        call_args = mock_consumer_class.call_args[0][0]
        assert 'stats_cb' in call_args


@pytest.mark.asyncio
async def test_stop_when_already_stopped(consumer):
    """Test stop when consumer is already stopped"""
    consumer._state = ConsumerState.STOPPED
    
    await consumer.stop()
    
    # State should remain STOPPED
    assert consumer._state == ConsumerState.STOPPED


@pytest.mark.asyncio
async def test_stop_when_stopping(consumer):
    """Test stop when consumer is already stopping"""
    consumer._state = ConsumerState.STOPPING
    
    await consumer.stop()
    
    # State should become STOPPED after completing stop
    assert consumer._state == ConsumerState.STOPPED


@pytest.mark.asyncio
async def test_stop_with_consume_task(consumer):
    """Test stop with active consume task"""
    consumer._state = ConsumerState.RUNNING
    consumer._running = True
    
    # Create a mock consume task that acts like a real task
    mock_task = Mock()
    mock_task.cancel = Mock()
    consumer._consume_task = mock_task
    
    # Create mock consumer
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    # Mock asyncio.gather to handle the cancelled task
    async def mock_gather(*args, **kwargs):
        return None
    
    with patch('asyncio.gather', side_effect=mock_gather):
        await consumer.stop()
    
    assert consumer._state == ConsumerState.STOPPED
    assert consumer._running is False
    mock_task.cancel.assert_called_once()
    mock_kafka_consumer.close.assert_called_once()
    assert consumer._consumer is None
    assert consumer._consume_task is None


@pytest.mark.asyncio
async def test_cleanup_with_consumer(consumer):
    """Test _cleanup when consumer exists"""
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    await consumer._cleanup()
    
    mock_kafka_consumer.close.assert_called_once()
    assert consumer._consumer is None


@pytest.mark.asyncio
async def test_cleanup_without_consumer(consumer):
    """Test _cleanup when consumer is None"""
    consumer._consumer = None
    
    # Should not raise any errors
    await consumer._cleanup()
    
    assert consumer._consumer is None


@pytest.mark.asyncio
async def test_consume_loop_debug_logging(consumer):
    """Test consume loop logs debug message every 100 polls"""
    consumer._running = True
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    # Mock poll to return None 150 times then stop
    poll_count = 0
    def mock_poll(timeout):
        nonlocal poll_count
        poll_count += 1
        if poll_count > 150:
            consumer._running = False
        return None
    
    mock_kafka_consumer.poll = mock_poll
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        with patch('asyncio.to_thread', side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)):
            await consumer._consume_loop()
        
        # Should have debug log at 100th poll
        debug_calls = [call for call in mock_logger.debug.call_args_list 
                       if "Consumer loop active" in str(call)]
        assert len(debug_calls) >= 1


@pytest.mark.asyncio
async def test_consume_loop_error_not_partition_eof(consumer):
    """Test consume loop handles non-EOF Kafka errors"""
    consumer._running = True
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    # Create mock message with error
    mock_msg = Mock(spec=Message)
    mock_error = Mock()
    mock_error.code.return_value = KafkaError.BROKER_NOT_AVAILABLE  # Not _PARTITION_EOF
    mock_msg.error.return_value = mock_error
    
    # Poll returns error message once then None
    poll_count = 0
    def mock_poll(timeout):
        nonlocal poll_count
        poll_count += 1
        if poll_count == 1:
            return mock_msg
        consumer._running = False
        return None
    
    mock_kafka_consumer.poll = mock_poll
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        with patch('asyncio.to_thread', side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)):
            await consumer._consume_loop()
    
    # Should log error and increment counter
    assert any("Consumer error" in str(call) for call in mock_logger.error.call_args_list)
    assert consumer._metrics.processing_errors == 1


@pytest.mark.asyncio
async def test_consume_loop_manual_commit(consumer):
    """Test consume loop with manual commit (auto_commit disabled)"""
    consumer._config.enable_auto_commit = False
    consumer._running = True
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    # Create mock message
    mock_msg = Mock(spec=Message)
    mock_msg.error.return_value = None
    mock_msg.topic.return_value = "test-topic"
    mock_msg.partition.return_value = 0
    mock_msg.offset.return_value = 100
    # Ensure schema registry returns a BaseEvent with required attributes
    ev = Mock(spec=BaseEvent)
    ev.event_type = "user_logged_in"
    ev.event_id = "e1"
    consumer._schema_registry.deserialize_event = Mock(return_value=ev)
    mock_msg.value.return_value = b"test_message"
    
    # Poll returns message once then None
    poll_count = 0
    def mock_poll(timeout):
        nonlocal poll_count
        poll_count += 1
        if poll_count == 1:
            return mock_msg
        consumer._running = False
        return None
    
    mock_kafka_consumer.poll = mock_poll
    
    with patch('asyncio.to_thread', side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)):
        await consumer._consume_loop()
    
    # Should call commit for the message
    mock_kafka_consumer.commit.assert_called_once_with(mock_msg)


@pytest.mark.asyncio
async def test_consume_loop_exit_logging(consumer):
    """Test consume loop logs warning when exiting"""
    consumer._running = False  # Start with running=False to exit immediately
    consumer._consumer = Mock()
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        await consumer._consume_loop()
    
    # Should log warning about loop ending
    warning_calls = [call for call in mock_logger.warning.call_args_list 
                     if "Consumer loop ended" in str(call)]
    assert len(warning_calls) == 1


@pytest.mark.asyncio
async def test_process_message_no_topic(consumer):
    """Test _process_message with message that has no topic"""
    mock_msg = Mock(spec=Message)
    mock_msg.topic.return_value = None
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        await consumer._process_message(mock_msg)
    
    mock_logger.warning.assert_called_with("Message with no topic received")


@pytest.mark.asyncio
async def test_process_message_empty_value(consumer):
    """Test _process_message with empty message value"""
    mock_msg = Mock(spec=Message)
    mock_msg.topic.return_value = "test-topic"
    mock_msg.value.return_value = None
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        await consumer._process_message(mock_msg)
    
    mock_logger.warning.assert_called_with("Empty message from topic test-topic")


@pytest.mark.asyncio
async def test_process_message_dispatcher_error_with_callback(consumer, mock_dispatcher):
    """Test _process_message when dispatcher raises error and error callback is set"""
    mock_msg = Mock(spec=Message)
    mock_msg.topic.return_value = "test-topic"
    ev = Mock(spec=BaseEvent); ev.event_type = "user_logged_in"; ev.event_id = "e1"
    consumer._schema_registry.deserialize_event = Mock(return_value=ev)
    mock_msg.value.return_value = b"test_message"
    
    # Make dispatcher raise an error
    mock_dispatcher.dispatch.side_effect = ValueError("Dispatch error")
    
    # Set error callback
    error_callback = AsyncMock()
    consumer.register_error_callback(error_callback)
    
    await consumer._process_message(mock_msg)
    
    # Should call error callback
    error_callback.assert_called_once()
    call_args = error_callback.call_args[0]
    assert isinstance(call_args[0], ValueError)
    assert str(call_args[0]) == "Dispatch error"
    
    # Should record error metrics
    assert consumer._metrics.processing_errors == 1


@pytest.mark.asyncio
async def test_process_message_dispatcher_error_without_callback(consumer, mock_dispatcher):
    """Test _process_message when dispatcher raises error and no error callback"""
    mock_msg = Mock(spec=Message)
    mock_msg.topic.return_value = "test-topic"
    ev = Mock(spec=BaseEvent); ev.event_type = "user_logged_in"; ev.event_id = "e1"
    consumer._schema_registry.deserialize_event = Mock(return_value=ev)
    mock_msg.value.return_value = b"test_message"
    
    # Make dispatcher raise an error
    mock_dispatcher.dispatch.side_effect = RuntimeError("Dispatch error")
    
    await consumer._process_message(mock_msg)
    
    # Should still record error metrics
    assert consumer._metrics.processing_errors == 1
    consumer._event_metrics.record_kafka_consumption_error.assert_called_once()


def test_register_error_callback(consumer):
    """Test register_error_callback"""
    callback = AsyncMock()
    consumer.register_error_callback(callback)
    
    assert consumer._error_callback == callback


def test_handle_stats_with_callback(consumer):
    """Test _handle_stats with stats callback"""
    stats_callback = Mock()
    consumer._stats_callback = stats_callback
    
    stats = {
        "rxmsgs": 100,
        "rxmsg_bytes": 10240,
        "topics": {
            "test-topic": {
                "partitions": {
                    "0": {"consumer_lag": 10},
                    "1": {"consumer_lag": 20},
                    "2": {"consumer_lag": -1}  # Negative lag should be ignored
                }
            }
        }
    }
    
    consumer._handle_stats(json.dumps(stats))
    
    assert consumer._metrics.messages_consumed == 100
    assert consumer._metrics.bytes_consumed == 10240
    assert consumer._metrics.consumer_lag == 30  # 10 + 20 (ignoring -1)
    assert consumer._metrics.last_updated is not None
    stats_callback.assert_called_once_with(stats)


def test_properties(consumer):
    """Test consumer property getters"""
    # Test state property
    consumer._state = ConsumerState.RUNNING
    assert consumer.state == ConsumerState.RUNNING
    
    # Test is_running property
    assert consumer.is_running is True
    consumer._state = ConsumerState.STOPPED
    assert consumer.is_running is False
    
    # Test metrics property
    assert isinstance(consumer.metrics, ConsumerMetrics)
    
    # Test consumer property
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    assert consumer.consumer == mock_kafka_consumer


def test_get_status(consumer):
    """Test get_status method"""
    consumer._state = ConsumerState.RUNNING
    consumer._metrics.messages_consumed = 100
    consumer._metrics.bytes_consumed = 10240
    consumer._metrics.consumer_lag = 5
    consumer._metrics.commit_failures = 2
    consumer._metrics.processing_errors = 3
    consumer._metrics.last_message_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    consumer._metrics.last_updated = datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc)
    
    status = consumer.get_status()
    
    assert status["state"] == ConsumerState.RUNNING.value
    assert status["is_running"] is True
    assert status["group_id"] == "test-group"
    assert status["client_id"] == "test-client"
    assert status["metrics"]["messages_consumed"] == 100
    assert status["metrics"]["bytes_consumed"] == 10240
    assert status["metrics"]["consumer_lag"] == 5
    assert status["metrics"]["commit_failures"] == 2
    assert status["metrics"]["processing_errors"] == 3
    assert status["metrics"]["last_message_time"] == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    assert status["metrics"]["last_updated"] == datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc).isoformat()


def test_get_status_no_timestamps(consumer):
    """Test get_status when timestamps are None"""
    consumer._metrics.last_message_time = None
    consumer._metrics.last_updated = None
    
    status = consumer.get_status()
    
    assert status["metrics"]["last_message_time"] is None
    assert status["metrics"]["last_updated"] is None


@pytest.mark.asyncio
async def test_seek_to_beginning(consumer):
    """Test seek_to_beginning"""
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    # Mock assignment
    mock_partition1 = Mock()
    mock_partition1.topic = "topic1"
    mock_partition1.partition = 0
    
    mock_partition2 = Mock()
    mock_partition2.topic = "topic2"
    mock_partition2.partition = 1
    
    mock_kafka_consumer.assignment.return_value = [mock_partition1, mock_partition2]
    
    await consumer.seek_to_beginning()
    
    # Should call seek for each partition with OFFSET_BEGINNING
    calls = mock_kafka_consumer.seek.call_args_list
    assert len(calls) == 2
    assert calls[0][0][0].topic == "topic1"
    assert calls[0][0][0].offset == OFFSET_BEGINNING
    assert calls[1][0][0].topic == "topic2"
    assert calls[1][0][0].offset == OFFSET_BEGINNING


@pytest.mark.asyncio
async def test_seek_to_end(consumer):
    """Test seek_to_end"""
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    # Mock assignment
    mock_partition = Mock()
    mock_partition.topic = "test-topic"
    mock_partition.partition = 0
    
    mock_kafka_consumer.assignment.return_value = [mock_partition]
    
    await consumer.seek_to_end()
    
    # Should call seek with OFFSET_END
    mock_kafka_consumer.seek.assert_called_once()
    call_args = mock_kafka_consumer.seek.call_args[0][0]
    assert call_args.topic == "test-topic"
    assert call_args.offset == OFFSET_END


def test_seek_all_partitions_no_consumer(consumer):
    """Test _seek_all_partitions when consumer is None"""
    consumer._consumer = None
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        consumer._seek_all_partitions(OFFSET_BEGINNING)
    
    mock_logger.warning.assert_called_with("Cannot seek: consumer not initialized")


@pytest.mark.asyncio
async def test_seek_to_offset(consumer):
    """Test seek_to_offset"""
    mock_kafka_consumer = Mock()
    consumer._consumer = mock_kafka_consumer
    
    await consumer.seek_to_offset("test-topic", 2, 500)
    
    # Should call seek with specific offset
    mock_kafka_consumer.seek.assert_called_once()
    call_args = mock_kafka_consumer.seek.call_args[0][0]
    assert call_args.topic == "test-topic"
    assert call_args.partition == 2
    assert call_args.offset == 500


@pytest.mark.asyncio
async def test_seek_to_offset_no_consumer(consumer):
    """Test seek_to_offset when consumer is None"""
    consumer._consumer = None
    
    with patch('app.events.core.consumer.logger') as mock_logger:
        await consumer.seek_to_offset("test-topic", 0, 100)
    
    mock_logger.warning.assert_called_with("Cannot seek to offset: consumer not initialized")
