"""Tests for app/events/core/producer.py - covering missing lines"""
import asyncio
import json
import socket
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, MagicMock, patch, PropertyMock, call
import pytest

from confluent_kafka import Message, Producer
from confluent_kafka.error import KafkaError

from app.events.core.producer import UnifiedProducer
from app.events.core.types import ProducerConfig, ProducerState, ProducerMetrics
from app.infrastructure.kafka.events.base import BaseEvent
from app.domain.enums.kafka import KafkaTopic


@pytest.fixture
def producer_config():
    """Create ProducerConfig"""
    config = Mock(spec=ProducerConfig)
    config.bootstrap_servers = "localhost:9092"
    config.client_id = "test-producer"
    config.batch_size = 1000
    config.compression_type = "gzip"
    config.to_producer_config.return_value = {
        "bootstrap.servers": "localhost:9092",
        "client.id": "test-producer"
    }
    return config


@pytest.fixture
def mock_schema_registry():
    """Mock SchemaRegistryManager"""
    registry = Mock()
    registry.serialize_event = Mock(return_value=b"serialized_event")
    return registry


@pytest.fixture
def mock_event_metrics():
    """Mock event metrics"""
    metrics = Mock()
    metrics.record_kafka_production_error = Mock()
    metrics.record_kafka_message_produced = Mock()
    return metrics


@pytest.fixture
def producer(producer_config, mock_schema_registry, mock_event_metrics):
    """Create UnifiedProducer with mocked dependencies"""
    with patch('app.events.core.producer.get_event_metrics', return_value=mock_event_metrics):
        return UnifiedProducer(
            config=producer_config,
            schema_registry_manager=mock_schema_registry,
            stats_callback=None
        )


@pytest.fixture
def mock_event():
    """Create a mock event"""
    event = Mock(spec=BaseEvent)
    event.event_id = "event_123"
    event.event_type = "execution_requested"
    event.topic = KafkaTopic.EXECUTION_EVENTS
    event.to_dict.return_value = {"event_id": "event_123"}
    return event


def test_producer_properties(producer):
    """Test producer property getters"""
    # Test is_running property
    assert producer.is_running is False
    producer._state = ProducerState.RUNNING
    assert producer.is_running is True
    
    # Test state property
    producer._state = ProducerState.STOPPED
    assert producer.state == ProducerState.STOPPED
    
    # Test metrics property
    assert isinstance(producer.metrics, ProducerMetrics)
    
    # Test producer property
    assert producer.producer is None
    mock_producer = Mock()
    producer._producer = mock_producer
    assert producer.producer == mock_producer


def test_handle_delivery_success_with_message_value(producer):
    """Test _handle_delivery when message has a value"""
    mock_message = Mock(spec=Message)
    mock_message.topic.return_value = "test-topic"
    mock_message.partition.return_value = 0
    mock_message.offset.return_value = 100
    mock_message.value.return_value = b"test_message_content"
    
    producer._handle_delivery(None, mock_message)
    
    assert producer._metrics.messages_sent == 1
    assert producer._metrics.bytes_sent == len(b"test_message_content")


def test_handle_delivery_success_without_message_value(producer):
    """Test _handle_delivery when message has no value"""
    mock_message = Mock(spec=Message)
    mock_message.topic.return_value = "test-topic"
    mock_message.partition.return_value = 0
    mock_message.offset.return_value = 100
    mock_message.value.return_value = None
    
    producer._handle_delivery(None, mock_message)
    
    assert producer._metrics.messages_sent == 1
    assert producer._metrics.bytes_sent == 0


def test_handle_stats_with_callback(producer):
    """Test _handle_stats with stats callback"""
    stats_callback = Mock()
    producer._stats_callback = stats_callback
    
    stats = {
        "msg_cnt": 10,
        "topics": {
            "test-topic": {
                "partitions": {
                    "0": {"msgq_cnt": 5, "rtt": {"avg": 100}},
                    "1": {"msgq_cnt": 3, "rtt": {"avg": 200}}
                }
            }
        }
    }
    
    producer._handle_stats(json.dumps(stats))
    
    assert producer._metrics.queue_size == 10
    # Average latency calculation: (100*5 + 200*3) / 8 = 1100/8 = 137.5
    assert producer._metrics.avg_latency_ms == (100*5 + 200*3) / (5+3)
    stats_callback.assert_called_once_with(stats)


def test_handle_stats_no_latency_data(producer):
    """Test _handle_stats when no latency data is available"""
    stats = {
        "msg_cnt": 5,
        "topics": {
            "test-topic": {
                "partitions": {
                    "0": {"msgq_cnt": 0}  # No rtt data
                }
            }
        }
    }
    
    producer._handle_stats(json.dumps(stats))
    
    assert producer._metrics.queue_size == 5
    assert producer._metrics.avg_latency_ms == 0  # No messages to calculate latency


def test_handle_stats_exception(producer):
    """Test _handle_stats with invalid JSON"""
    with patch('app.events.core.producer.logger') as mock_logger:
        producer._handle_stats("invalid json")
        
        mock_logger.error.assert_called_once()
        assert "Error parsing producer stats" in str(mock_logger.error.call_args)


@pytest.mark.asyncio
async def test_start_already_running(producer):
    """Test start when producer is already running"""
    producer._state = ProducerState.RUNNING
    
    with patch('app.events.core.producer.logger') as mock_logger:
        await producer.start()
        
        mock_logger.warning.assert_called_once()
        assert "already in state" in str(mock_logger.warning.call_args)


@pytest.mark.asyncio
async def test_start_from_error_state(producer):
    """Test start from ERROR state"""
    producer._state = ProducerState.ERROR
    
    with patch('app.events.core.producer.Producer') as mock_producer_class:
        mock_producer = Mock()
        mock_producer_class.return_value = mock_producer
        
        await producer.start()
        
        assert producer._state == ProducerState.RUNNING
        assert producer._producer == mock_producer
        assert producer._running is True


def test_get_status(producer):
    """Test get_status method"""
    # Set up metrics
    producer._metrics.messages_sent = 100
    producer._metrics.messages_failed = 5
    producer._metrics.bytes_sent = 10240
    producer._metrics.queue_size = 3
    producer._metrics.avg_latency_ms = 50.5
    producer._metrics.last_error = "Test error"
    producer._metrics.last_error_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    status = producer.get_status()
    
    assert status["state"] == ProducerState.STOPPED.value
    assert status["running"] is False
    assert status["config"]["bootstrap_servers"] == "localhost:9092"
    assert status["metrics"]["messages_sent"] == 100
    assert status["metrics"]["messages_failed"] == 5
    assert status["metrics"]["bytes_sent"] == 10240
    assert status["metrics"]["queue_size"] == 3
    assert status["metrics"]["avg_latency_ms"] == 50.5
    assert status["metrics"]["last_error"] == "Test error"
    assert status["metrics"]["last_error_time"] == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()


def test_get_status_no_error_time(producer):
    """Test get_status when last_error_time is None"""
    producer._metrics.last_error_time = None
    
    status = producer.get_status()
    
    assert status["metrics"]["last_error_time"] is None


@pytest.mark.asyncio
async def test_stop_already_stopped(producer):
    """Test stop when producer is already stopped"""
    producer._state = ProducerState.STOPPED
    
    with patch('app.events.core.producer.logger') as mock_logger:
        await producer.stop()
        
        mock_logger.info.assert_called()
        assert "already in state" in str(mock_logger.info.call_args[0])


@pytest.mark.asyncio
async def test_stop_already_stopping(producer):
    """Test stop when producer is already stopping"""
    producer._state = ProducerState.STOPPING
    
    with patch('app.events.core.producer.logger') as mock_logger:
        await producer.stop()
        
        mock_logger.info.assert_called()
        assert "already in state" in str(mock_logger.info.call_args[0])


@pytest.mark.asyncio
async def test_stop_with_poll_task(producer):
    """Test stop with active poll task"""
    producer._state = ProducerState.RUNNING
    producer._running = True
    
    # Create a mock poll task that acts like a real task
    mock_poll_task = Mock()
    mock_poll_task.cancel = Mock()
    producer._poll_task = mock_poll_task
    
    # Create mock producer
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    
    # Mock asyncio.gather to handle the cancelled task
    async def mock_gather(*args, **kwargs):
        return None
    
    with patch('asyncio.gather', side_effect=mock_gather):
        await producer.stop()
    
    assert producer._state == ProducerState.STOPPED
    assert producer._running is False
    mock_poll_task.cancel.assert_called_once()
    mock_kafka_producer.flush.assert_called_once_with(timeout=10.0)
    assert producer._producer is None
    assert producer._poll_task is None


@pytest.mark.asyncio
async def test_poll_loop(producer):
    """Test _poll_loop operation"""
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    producer._running = True
    
    # Run poll loop for a short time
    poll_task = asyncio.create_task(producer._poll_loop())
    
    # Let it run briefly
    await asyncio.sleep(0.05)
    
    # Stop it
    producer._running = False
    await poll_task
    
    # Check that poll was called
    assert mock_kafka_producer.poll.called


@pytest.mark.asyncio
async def test_poll_loop_exits_when_producer_none(producer):
    """Test _poll_loop exits when producer becomes None"""
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    producer._running = True
    
    # Start poll loop
    poll_task = asyncio.create_task(producer._poll_loop())
    
    # Let it run briefly
    await asyncio.sleep(0.02)
    
    # Set producer to None
    producer._producer = None
    
    # Should exit
    await poll_task


@pytest.mark.asyncio
async def test_produce_no_producer(producer, mock_event):
    """Test produce when producer is not running"""
    producer._producer = None
    
    with patch('app.events.core.producer.logger') as mock_logger:
        await producer.produce(mock_event)
        
        mock_logger.error.assert_called_once_with("Producer not running")


@pytest.mark.asyncio
async def test_produce_with_headers(producer, mock_event):
    """Test produce with headers"""
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    
    headers = {"header1": "value1", "header2": "value2"}
    
    await producer.produce(mock_event, key="test_key", headers=headers)
    
    # Check produce was called with encoded headers
    call_args = mock_kafka_producer.produce.call_args
    assert call_args[1]["headers"] == [
        ("header1", b"value1"),
        ("header2", b"value2")
    ]


@pytest.mark.asyncio
async def test_send_to_dlq_no_producer(producer, mock_event):
    """Test send_to_dlq when producer is not running"""
    producer._producer = None
    
    with patch('app.events.core.producer.logger') as mock_logger:
        await producer.send_to_dlq(
            original_event=mock_event,
            original_topic="test-topic",
            error=Exception("Test error"),
            retry_count=1
        )
        
        mock_logger.error.assert_called_once_with("Producer not running, cannot send to DLQ")


@pytest.mark.asyncio
async def test_send_to_dlq_success(producer, mock_event):
    """Test successful send_to_dlq"""
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    
    with patch('socket.gethostname', return_value='test-host'):
        with patch('asyncio.current_task') as mock_current_task:
            mock_task = Mock()
            mock_task.get_name.return_value = 'test-task'
            mock_current_task.return_value = mock_task
            
            await producer.send_to_dlq(
                original_event=mock_event,
                original_topic="test-topic",
                error=ValueError("Test error"),
                retry_count=2
            )
    
    # Verify produce was called
    mock_kafka_producer.produce.assert_called_once()
    call_args = mock_kafka_producer.produce.call_args
    
    assert call_args[1]["topic"] == str(KafkaTopic.DEAD_LETTER_QUEUE)
    assert call_args[1]["key"] == b"event_123"
    
    # Check headers
    headers = call_args[1]["headers"]
    assert ("original_topic", b"test-topic") in headers
    assert ("error_type", b"ValueError") in headers
    assert ("retry_count", b"2") in headers


@pytest.mark.asyncio
async def test_send_to_dlq_exception(producer, mock_event):
    """Test send_to_dlq when an exception occurs"""
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    
    # Make produce raise an exception
    mock_kafka_producer.produce.side_effect = Exception("Kafka error")
    
    with patch('app.events.core.producer.logger') as mock_logger:
        with patch('socket.gethostname', return_value='test-host'):
            await producer.send_to_dlq(
                original_event=mock_event,
                original_topic="test-topic",
                error=ValueError("Original error"),
                retry_count=1
            )
    
    # Should log critical error
    mock_logger.critical.assert_called_once()
    assert "Failed to send event" in str(mock_logger.critical.call_args)
    assert producer._metrics.messages_failed == 1


@pytest.mark.asyncio
async def test_send_to_dlq_no_current_task(producer, mock_event):
    """Test send_to_dlq when no current task exists"""
    mock_kafka_producer = Mock()
    producer._producer = mock_kafka_producer
    
    with patch('socket.gethostname', return_value='test-host'):
        with patch('asyncio.current_task', return_value=None):
            await producer.send_to_dlq(
                original_event=mock_event,
                original_topic="test-topic",
                error=Exception("Test error"),
                retry_count=0
            )
    
    # Should still work with 'main' as task name
    mock_kafka_producer.produce.assert_called_once()
    
    # Check the value contains 'test-host-main' as producer_id
    call_args = mock_kafka_producer.produce.call_args
    value_str = call_args[1]["value"].decode('utf-8')
    value_dict = json.loads(value_str)
    assert value_dict["producer_id"] == "test-host-main"