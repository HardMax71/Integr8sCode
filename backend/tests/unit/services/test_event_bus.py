import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
from contextlib import AsyncExitStack

import pytest
from confluent_kafka import KafkaError
from starlette.requests import Request

from app.services.event_bus import EventBus, EventBusManager, Subscription, get_event_bus


@pytest.fixture
def mock_settings():
    """Create mock settings"""
    settings = Mock()
    settings.KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
    return settings


@pytest.fixture
def mock_metrics():
    """Create mock metrics"""
    metrics = Mock()
    metrics.update_event_bus_subscribers = Mock()
    return metrics


@pytest.fixture
def event_bus(mock_settings, mock_metrics):
    """Create EventBus with mocked dependencies"""
    with patch('app.services.event_bus.get_settings', return_value=mock_settings):
        with patch('app.services.event_bus.get_connection_metrics', return_value=mock_metrics):
            bus = EventBus()
            return bus


@pytest.mark.asyncio
async def test_event_bus_initialization(event_bus):
    """Test EventBus initialization"""
    assert event_bus.producer is None
    assert event_bus.consumer is None
    assert event_bus._running is False
    assert len(event_bus._subscriptions) == 0
    assert len(event_bus._pattern_index) == 0


@pytest.mark.asyncio
async def test_event_bus_start_when_not_running(event_bus):
    """Test starting the event bus"""
    with patch.object(event_bus, '_initialize_kafka', new_callable=AsyncMock) as mock_init:
        with patch('asyncio.create_task') as mock_create_task:
            await event_bus.start()
            
            assert event_bus._running is True
            mock_init.assert_called_once()
            mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_event_bus_start_when_already_running(event_bus):
    """Test starting event bus when already running"""
    event_bus._running = True
    
    with patch.object(event_bus, '_initialize_kafka', new_callable=AsyncMock) as mock_init:
        await event_bus.start()
        
        # Should not initialize again
        mock_init.assert_not_called()


@pytest.mark.asyncio
async def test_initialize_kafka(event_bus):
    """Test Kafka initialization"""
    with patch('app.services.event_bus.Producer') as mock_producer:
        with patch('app.services.event_bus.Consumer') as mock_consumer:
            mock_consumer_instance = Mock()
            mock_consumer.return_value = mock_consumer_instance
            
            await event_bus._initialize_kafka()
            
            assert event_bus.producer is not None
            assert event_bus.consumer is not None
            mock_consumer_instance.subscribe.assert_called_once_with(['event_bus_stream'])
            assert event_bus._executor is not None


@pytest.mark.asyncio
async def test_stop_event_bus(event_bus):
    """Test stopping the event bus"""
    with patch.object(event_bus, '_cleanup', new_callable=AsyncMock) as mock_cleanup:
        await event_bus.stop()
        mock_cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup(event_bus):
    """Test cleanup of resources"""
    # Setup mock resources
    # Create a real async task that can be cancelled
    async def dummy_task():
        await asyncio.sleep(10)  # Long sleep to ensure it's cancelled
    
    event_bus._consumer_task = asyncio.create_task(dummy_task())
    
    mock_consumer = Mock()
    event_bus.consumer = mock_consumer
    
    mock_producer = Mock()
    event_bus.producer = mock_producer
    
    event_bus._running = True
    event_bus._subscriptions = {"sub1": Mock()}
    event_bus._pattern_index = {"pattern1": {"sub1"}}
    
    await event_bus._cleanup()
    
    assert event_bus._running is False
    assert event_bus._consumer_task.cancelled()  # Check task was cancelled
    mock_consumer.close.assert_called_once()
    mock_producer.flush.assert_called_once_with(timeout=5)
    assert event_bus.consumer is None
    assert event_bus.producer is None
    assert len(event_bus._subscriptions) == 0
    assert len(event_bus._pattern_index) == 0


@pytest.mark.asyncio
async def test_cleanup_with_cancelled_error(event_bus):
    """Test cleanup when consumer task raises CancelledError"""
    # Create a real async task that's already done
    async def already_cancelled_task():
        raise asyncio.CancelledError()
    
    try:
        event_bus._consumer_task = asyncio.create_task(already_cancelled_task())
        await event_bus._consumer_task
    except asyncio.CancelledError:
        pass  # Expected
    
    await event_bus._cleanup()
    
    # Task should already be cancelled/done
    assert event_bus._consumer_task.done()


@pytest.mark.asyncio
async def test_publish_with_kafka(event_bus):
    """Test publishing event with Kafka"""
    mock_producer = Mock()
    event_bus.producer = mock_producer
    event_bus._executor = AsyncMock()
    
    with patch.object(event_bus, '_distribute_event', new_callable=AsyncMock) as mock_distribute:
        await event_bus.publish("test.event", {"data": "test"})
        
        mock_distribute.assert_called_once()
        event_bus._executor.assert_called()


@pytest.mark.asyncio
async def test_publish_without_executor(event_bus):
    """Test publishing when executor is not available"""
    mock_producer = Mock()
    event_bus.producer = mock_producer
    event_bus._executor = None
    
    with patch.object(event_bus, '_distribute_event', new_callable=AsyncMock):
        await event_bus.publish("test.event", {"data": "test"})
        
        mock_producer.produce.assert_called_once()
        mock_producer.poll.assert_called_once_with(0)


@pytest.mark.asyncio
async def test_publish_kafka_error(event_bus):
    """Test publishing with Kafka error"""
    mock_producer = Mock()
    mock_producer.produce.side_effect = Exception("Kafka error")
    event_bus.producer = mock_producer
    event_bus._executor = None
    
    with patch.object(event_bus, '_distribute_event', new_callable=AsyncMock) as mock_distribute:
        # Should not raise, just log error
        await event_bus.publish("test.event", {"data": "test"})
        
        # Should still distribute locally
        mock_distribute.assert_called_once()


@pytest.mark.asyncio
async def test_create_event(event_bus):
    """Test event creation"""
    event = event_bus._create_event("test.type", {"key": "value"})
    
    assert "id" in event
    assert event["event_type"] == "test.type"
    assert "timestamp" in event
    assert event["payload"] == {"key": "value"}


@pytest.mark.asyncio
async def test_subscribe(event_bus):
    """Test subscribing to events"""
    handler = AsyncMock()
    
    sub_id = await event_bus.subscribe("test.*", handler)
    
    assert sub_id in event_bus._subscriptions
    assert event_bus._subscriptions[sub_id].pattern == "test.*"
    assert event_bus._subscriptions[sub_id].handler == handler
    assert "test.*" in event_bus._pattern_index
    assert sub_id in event_bus._pattern_index["test.*"]
    
    # Verify metrics update
    event_bus.metrics.update_event_bus_subscribers.assert_called()


@pytest.mark.asyncio
async def test_subscribe_multiple_same_pattern(event_bus):
    """Test multiple subscriptions to same pattern"""
    handler1 = AsyncMock()
    handler2 = AsyncMock()
    
    sub_id1 = await event_bus.subscribe("test.*", handler1)
    sub_id2 = await event_bus.subscribe("test.*", handler2)
    
    assert sub_id1 != sub_id2
    assert len(event_bus._pattern_index["test.*"]) == 2
    assert sub_id1 in event_bus._pattern_index["test.*"]
    assert sub_id2 in event_bus._pattern_index["test.*"]


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    """Test unsubscribing from events"""
    handler = AsyncMock()
    
    # Subscribe first
    sub_id = await event_bus.subscribe("test.*", handler)
    
    # Unsubscribe
    await event_bus.unsubscribe("test.*", handler)
    
    assert sub_id not in event_bus._subscriptions
    assert "test.*" not in event_bus._pattern_index


@pytest.mark.asyncio
async def test_unsubscribe_not_found(event_bus):
    """Test unsubscribing when subscription not found"""
    handler = AsyncMock()
    
    # Should not raise, just log warning
    await event_bus.unsubscribe("test.*", handler)


@pytest.mark.asyncio
async def test_remove_subscription(event_bus):
    """Test removing subscription by ID"""
    handler = AsyncMock()
    sub_id = await event_bus.subscribe("test.*", handler)
    
    async with event_bus._lock:
        await event_bus._remove_subscription(sub_id)
    
    assert sub_id not in event_bus._subscriptions
    assert "test.*" not in event_bus._pattern_index


@pytest.mark.asyncio
async def test_remove_subscription_not_found(event_bus):
    """Test removing non-existent subscription"""
    async with event_bus._lock:
        # Should not raise, just log warning
        await event_bus._remove_subscription("non_existent")


@pytest.mark.asyncio
async def test_distribute_event(event_bus):
    """Test distributing events to handlers"""
    handler1 = AsyncMock()
    handler2 = AsyncMock()
    
    await event_bus.subscribe("test.*", handler1)
    await event_bus.subscribe("test.specific", handler2)
    
    event = {"event_type": "test.specific", "data": "test"}
    
    await event_bus._distribute_event("test.specific", event)
    
    handler1.assert_called_once_with(event)
    handler2.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_distribute_event_handler_error(event_bus):
    """Test distributing events when handler raises error"""
    handler1 = AsyncMock()
    handler2 = AsyncMock(side_effect=Exception("Handler error"))
    
    await event_bus.subscribe("test.*", handler1)
    await event_bus.subscribe("test.*", handler2)
    
    event = {"event_type": "test.event", "data": "test"}
    
    # Should not raise, errors are handled
    await event_bus._distribute_event("test.event", event)
    
    handler1.assert_called_once_with(event)
    handler2.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_find_matching_handlers(event_bus):
    """Test finding handlers matching event type"""
    handler1 = AsyncMock()
    handler2 = AsyncMock()
    handler3 = AsyncMock()
    
    await event_bus.subscribe("test.*", handler1)
    await event_bus.subscribe("*.specific", handler2)
    await event_bus.subscribe("other.*", handler3)
    
    handlers = await event_bus._find_matching_handlers("test.specific")
    
    assert handler1 in handlers
    assert handler2 in handlers
    assert handler3 not in handlers


@pytest.mark.asyncio
async def test_invoke_handler_async(event_bus):
    """Test invoking async handler"""
    handler = AsyncMock()
    event = {"test": "data"}
    
    await event_bus._invoke_handler(handler, event)
    
    handler.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_invoke_handler_sync(event_bus):
    """Test invoking sync handler"""
    handler = Mock()  # Sync handler
    event = {"test": "data"}
    
    with patch('asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
        await event_bus._invoke_handler(handler, event)
        mock_to_thread.assert_called_once_with(handler, event)


@pytest.mark.asyncio
async def test_kafka_listener_no_consumer(event_bus):
    """Test Kafka listener when consumer is None"""
    event_bus.consumer = None
    
    # Should return immediately
    await event_bus._kafka_listener()


@pytest.mark.asyncio
async def test_kafka_listener_with_messages(event_bus):
    """Test Kafka listener processing messages"""
    mock_consumer = Mock()
    event_bus.consumer = mock_consumer
    event_bus._running = True
    event_bus._executor = AsyncMock()
    
    # Create mock message
    mock_msg = Mock()
    mock_msg.error.return_value = None
    mock_msg.value.return_value = json.dumps({
        "event_type": "test.event",
        "payload": {"data": "test"}
    }).encode('utf-8')
    
    # Simulate one message then stop
    event_bus._executor.side_effect = [mock_msg, None, asyncio.CancelledError()]
    
    with patch.object(event_bus, '_distribute_event', new_callable=AsyncMock) as mock_distribute:
        try:
            await event_bus._kafka_listener()
        except asyncio.CancelledError:
            pass
        
        mock_distribute.assert_called_once()


@pytest.mark.asyncio
async def test_kafka_listener_with_error_message(event_bus):
    """Test Kafka listener with error message"""
    mock_consumer = Mock()
    event_bus.consumer = mock_consumer
    event_bus._running = True
    event_bus._executor = AsyncMock()
    
    # Create mock error message
    mock_error = Mock()
    mock_error.code.return_value = KafkaError.BROKER_NOT_AVAILABLE
    mock_msg = Mock()
    mock_msg.error.return_value = mock_error
    
    # Simulate error then stop
    event_bus._executor.side_effect = [mock_msg, asyncio.CancelledError()]
    
    try:
        await event_bus._kafka_listener()
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_kafka_listener_deserialization_error(event_bus):
    """Test Kafka listener with deserialization error"""
    mock_consumer = Mock()
    event_bus.consumer = mock_consumer
    event_bus._running = True
    event_bus._executor = AsyncMock()
    
    # Create mock message with invalid JSON
    mock_msg = Mock()
    mock_msg.error.return_value = None
    mock_msg.value.return_value = b"invalid json"
    
    # Simulate invalid message then stop
    event_bus._executor.side_effect = [mock_msg, asyncio.CancelledError()]
    
    try:
        await event_bus._kafka_listener()
    except asyncio.CancelledError:
        pass
    # Should handle error gracefully


@pytest.mark.asyncio
async def test_kafka_listener_fatal_error(event_bus):
    """Test Kafka listener with fatal error"""
    mock_consumer = Mock()
    event_bus.consumer = mock_consumer
    event_bus._running = True
    event_bus._executor = AsyncMock()
    event_bus._executor.side_effect = Exception("Fatal error")
    
    await event_bus._kafka_listener()
    
    assert event_bus._running is False


@pytest.mark.asyncio
async def test_update_metrics(event_bus):
    """Test metrics update"""
    event_bus._pattern_index = {
        "test.*": {"sub1", "sub2"},
        "other.*": {"sub3"}
    }
    
    event_bus._update_metrics("test.*")
    
    event_bus.metrics.update_event_bus_subscribers.assert_called_with(2, "test.*")


@pytest.mark.asyncio
async def test_update_metrics_no_metrics(event_bus):
    """Test metrics update when metrics is None"""
    event_bus.metrics = None
    
    # Should not raise
    event_bus._update_metrics("test.*")


@pytest.mark.asyncio
async def test_get_statistics(event_bus):
    """Test getting event bus statistics"""
    # Setup some subscriptions
    handler = AsyncMock()
    await event_bus.subscribe("test.*", handler)
    await event_bus.subscribe("other.*", handler)
    
    event_bus.producer = Mock()
    event_bus._running = True
    
    stats = await event_bus.get_statistics()
    
    assert stats["total_patterns"] == 2
    assert stats["total_subscriptions"] == 2
    assert stats["kafka_enabled"] is True
    assert stats["running"] is True
    assert "test.*" in stats["patterns"]
    assert "other.*" in stats["patterns"]


@pytest.mark.asyncio
async def test_event_bus_manager_init():
    """Test EventBusManager initialization"""
    manager = EventBusManager()
    assert manager._event_bus is None


@pytest.mark.asyncio
async def test_event_bus_manager_get_event_bus():
    """Test getting event bus from manager"""
    manager = EventBusManager()
    
    with patch('app.services.event_bus.EventBus') as mock_bus_class:
        mock_bus = Mock()
        mock_bus.start = AsyncMock()
        mock_bus_class.return_value = mock_bus
        
        bus1 = await manager.get_event_bus()
        bus2 = await manager.get_event_bus()
        
        # Should be the same instance (singleton)
        assert bus1 == bus2
        assert bus1 == mock_bus
        
        # Should only create and start once
        mock_bus_class.assert_called_once()
        mock_bus.start.assert_called_once()


@pytest.mark.asyncio
async def test_event_bus_manager_close():
    """Test closing event bus manager"""
    manager = EventBusManager()
    
    mock_bus = Mock()
    mock_bus.stop = AsyncMock()
    manager._event_bus = mock_bus
    
    await manager.close()
    
    mock_bus.stop.assert_called_once()
    assert manager._event_bus is None


@pytest.mark.asyncio
async def test_event_bus_manager_close_no_bus():
    """Test closing manager when no bus exists"""
    manager = EventBusManager()
    
    # Should not raise
    await manager.close()


@pytest.mark.asyncio
async def test_event_bus_context():
    """Test event bus context manager"""
    manager = EventBusManager()
    
    with patch.object(manager, 'get_event_bus', new_callable=AsyncMock) as mock_get:
        with patch.object(manager, 'close', new_callable=AsyncMock) as mock_close:
            mock_bus = Mock()
            mock_get.return_value = mock_bus
            
            async with manager.event_bus_context() as bus:
                assert bus == mock_bus
            
            mock_get.assert_called_once()
            mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_get_event_bus_from_request():
    """Test getting event bus from request"""
    request = Mock(spec=Request)
    manager = Mock(spec=EventBusManager)
    mock_bus = Mock()
    manager.get_event_bus = AsyncMock(return_value=mock_bus)
    request.app.state.event_bus_manager = manager
    
    bus = await get_event_bus(request)
    
    assert bus == mock_bus
    manager.get_event_bus.assert_called_once()


@pytest.mark.asyncio
async def test_full_publish_subscribe_flow(event_bus):
    """Test complete publish-subscribe flow"""
    received_events = []
    
    async def handler(event):
        received_events.append(event)
    
    # Subscribe to events
    await event_bus.subscribe("user.*", handler)
    await event_bus.subscribe("*.created", handler)
    
    # Publish matching event
    await event_bus.publish("user.created", {"user_id": "123"})
    
    # Allow async operations to complete
    await asyncio.sleep(0.1)
    
    # Should receive event twice (matches both patterns)
    assert len(received_events) == 2
    assert received_events[0]["event_type"] == "user.created"
    assert received_events[0]["payload"]["user_id"] == "123"


@pytest.mark.asyncio
async def test_concurrent_subscriptions_and_unsubscriptions(event_bus):
    """Test concurrent subscription and unsubscription operations"""
    handlers = [AsyncMock() for _ in range(10)]
    
    # Subscribe concurrently
    sub_tasks = [
        event_bus.subscribe(f"pattern.{i}", handler)
        for i, handler in enumerate(handlers)
    ]
    sub_ids = await asyncio.gather(*sub_tasks)
    
    assert len(event_bus._subscriptions) == 10
    assert len(event_bus._pattern_index) == 10
    
    # Unsubscribe concurrently
    unsub_tasks = [
        event_bus.unsubscribe(f"pattern.{i}", handler)
        for i, handler in enumerate(handlers)
    ]
    await asyncio.gather(*unsub_tasks)
    
    assert len(event_bus._subscriptions) == 0
    assert len(event_bus._pattern_index) == 0