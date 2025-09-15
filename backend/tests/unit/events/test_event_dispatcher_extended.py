"""Extended tests for EventDispatcher to achieve high coverage."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import EventDispatcher
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent, ExecutionCompletedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


def make_execution_requested_event() -> ExecutionRequestedEvent:
    """Create a sample ExecutionRequestedEvent."""
    return ExecutionRequestedEvent(
        execution_id="test-exec-1",
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
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )


def make_execution_completed_event() -> ExecutionCompletedEvent:
    """Create a sample ExecutionCompletedEvent."""
    return ExecutionCompletedEvent(
        execution_id="test-exec-1",
        output="hello",
        exit_code=0,
        start_time="2025-01-01T00:00:00Z",
        end_time="2025-01-01T00:00:10Z",
        duration_ms=10000,
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )


class TestEventDispatcherExtended:
    """Extended tests for EventDispatcher."""

    @pytest.fixture
    def dispatcher(self):
        """Create a fresh dispatcher for each test."""
        return EventDispatcher()

    @pytest.fixture
    def mock_handler(self):
        """Create a mock async handler."""
        handler = AsyncMock()
        handler.__name__ = "mock_handler"
        handler.__class__.__name__ = "MockHandler"
        return handler

    @pytest.fixture
    def failing_handler(self):
        """Create a handler that always fails."""
        async def handler(event: BaseEvent):
            raise ValueError("Handler failed")
        handler.__name__ = "failing_handler"
        return handler

    def test_remove_handler_not_found(self, dispatcher):
        """Test remove_handler returns False when handler not found."""
        async def nonexistent_handler(event: BaseEvent):
            pass

        # Try to remove a handler that was never registered
        result = dispatcher.remove_handler(EventType.EXECUTION_REQUESTED, nonexistent_handler)
        assert result is False

    def test_remove_handler_wrong_event_type(self, dispatcher, mock_handler):
        """Test remove_handler returns False when handler registered for different event type."""
        # Register handler for EXECUTION_REQUESTED
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, mock_handler)

        # Try to remove it from EXECUTION_COMPLETED
        result = dispatcher.remove_handler(EventType.EXECUTION_COMPLETED, mock_handler)
        assert result is False

    def test_remove_handler_cleans_empty_list(self, dispatcher, mock_handler):
        """Test remove_handler removes empty list from _handlers dict."""
        # Register and then remove a handler
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, mock_handler)
        assert EventType.EXECUTION_REQUESTED in dispatcher._handlers

        result = dispatcher.remove_handler(EventType.EXECUTION_REQUESTED, mock_handler)
        assert result is True
        assert EventType.EXECUTION_REQUESTED not in dispatcher._handlers

    @pytest.mark.asyncio
    async def test_dispatch_with_failing_handler(self, dispatcher, failing_handler):
        """Test dispatch increments failed metric when handler raises exception."""
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, failing_handler)

        event = make_execution_requested_event()
        await dispatcher.dispatch(event)

        metrics = dispatcher.get_metrics()
        assert metrics[EventType.EXECUTION_REQUESTED.value]["failed"] >= 1
        assert metrics[EventType.EXECUTION_REQUESTED.value]["processed"] == 0

    @pytest.mark.asyncio
    async def test_dispatch_mixed_success_and_failure(self, dispatcher, mock_handler, failing_handler):
        """Test dispatch with both successful and failing handlers."""
        # Register both handlers
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, mock_handler)
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, failing_handler)

        event = make_execution_requested_event()
        await dispatcher.dispatch(event)

        metrics = dispatcher.get_metrics()
        # One should succeed, one should fail
        assert metrics[EventType.EXECUTION_REQUESTED.value]["failed"] >= 1
        assert metrics[EventType.EXECUTION_REQUESTED.value]["processed"] >= 1

    @pytest.mark.asyncio
    async def test_execute_handler_exception_logging(self, dispatcher):
        """Test _execute_handler logs exceptions properly."""
        async def failing_handler(event: BaseEvent):
            raise ValueError("Handler failed")

        event = make_execution_requested_event()

        with pytest.raises(ValueError, match="Handler failed"):
            await dispatcher._execute_handler(failing_handler, event)

    @pytest.mark.asyncio
    async def test_execute_handler_success_logging(self, dispatcher, mock_handler):
        """Test _execute_handler logs successful execution."""
        event = make_execution_requested_event()
        mock_handler.return_value = "Success"

        await dispatcher._execute_handler(mock_handler, event)
        mock_handler.assert_called_once_with(event)

    def test_get_topics_for_registered_handlers(self, dispatcher, mock_handler):
        """Test get_topics_for_registered_handlers returns correct topics."""
        # Register handlers for different event types
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, mock_handler)
        dispatcher.register_handler(EventType.EXECUTION_COMPLETED, mock_handler)

        topics = dispatcher.get_topics_for_registered_handlers()

        # Both events should result in topic(s) being returned
        assert len(topics) >= 1
        # The actual topic string contains the full topic path, check if any match
        assert any('execution' in topic for topic in topics)

    def test_get_topics_for_registered_handlers_empty(self, dispatcher):
        """Test get_topics_for_registered_handlers with no handlers."""
        topics = dispatcher.get_topics_for_registered_handlers()
        assert topics == set()

    def test_get_topics_for_registered_handlers_invalid_event_type(self, dispatcher, mock_handler):
        """Test get_topics_for_registered_handlers with unmapped event type."""
        # Mock get_event_class_for_type to return None
        with patch('app.events.core.dispatcher.get_event_class_for_type', return_value=None):
            dispatcher.register_handler(EventType.EXECUTION_REQUESTED, mock_handler)
            topics = dispatcher.get_topics_for_registered_handlers()
            assert topics == set()

    def test_clear_handlers(self, dispatcher, mock_handler):
        """Test clear_handlers removes all handlers."""
        # Register multiple handlers
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, mock_handler)
        dispatcher.register_handler(EventType.EXECUTION_COMPLETED, mock_handler)
        dispatcher.register_handler(EventType.EXECUTION_FAILED, mock_handler)

        # Verify handlers are registered
        assert len(dispatcher._handlers) >= 3

        # Clear all handlers
        dispatcher.clear_handlers()

        # Verify all handlers are removed
        assert len(dispatcher._handlers) == 0
        assert dispatcher.get_handlers(EventType.EXECUTION_REQUESTED) == []
        assert dispatcher.get_handlers(EventType.EXECUTION_COMPLETED) == []

    def test_get_all_handlers(self, dispatcher, mock_handler):
        """Test get_all_handlers returns copy of all handlers."""
        # Register handlers
        handler1 = AsyncMock()
        handler1.__name__ = "handler1"
        handler2 = AsyncMock()
        handler2.__name__ = "handler2"

        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, handler1)
        dispatcher.register_handler(EventType.EXECUTION_COMPLETED, handler2)

        all_handlers = dispatcher.get_all_handlers()

        # Verify we got the handlers
        assert EventType.EXECUTION_REQUESTED in all_handlers
        assert EventType.EXECUTION_COMPLETED in all_handlers
        assert handler1 in all_handlers[EventType.EXECUTION_REQUESTED]
        assert handler2 in all_handlers[EventType.EXECUTION_COMPLETED]

        # Verify it's a copy (modifying returned dict doesn't affect original)
        all_handlers[EventType.EXECUTION_REQUESTED].clear()
        assert len(dispatcher.get_handlers(EventType.EXECUTION_REQUESTED)) == 1

    def test_get_all_handlers_empty(self, dispatcher):
        """Test get_all_handlers with no handlers registered."""
        all_handlers = dispatcher.get_all_handlers()
        assert all_handlers == {}

    def test_replace_handlers(self, dispatcher, mock_handler):
        """Test replace_handlers replaces all handlers for an event type."""
        # Register initial handlers
        handler1 = AsyncMock()
        handler1.__name__ = "handler1"
        handler2 = AsyncMock()
        handler2.__name__ = "handler2"

        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, handler1)
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, handler2)

        # Verify initial state
        assert len(dispatcher.get_handlers(EventType.EXECUTION_REQUESTED)) == 2

        # Replace with new handlers
        new_handler1 = AsyncMock()
        new_handler1.__name__ = "new_handler1"
        new_handler2 = AsyncMock()
        new_handler2.__name__ = "new_handler2"
        new_handler3 = AsyncMock()
        new_handler3.__name__ = "new_handler3"

        new_handlers = [new_handler1, new_handler2, new_handler3]
        dispatcher.replace_handlers(EventType.EXECUTION_REQUESTED, new_handlers)

        # Verify handlers were replaced
        current_handlers = dispatcher.get_handlers(EventType.EXECUTION_REQUESTED)
        assert len(current_handlers) == 3
        assert handler1 not in current_handlers
        assert handler2 not in current_handlers
        assert new_handler1 in current_handlers
        assert new_handler2 in current_handlers
        assert new_handler3 in current_handlers

    def test_replace_handlers_new_event_type(self, dispatcher):
        """Test replace_handlers can add handlers for a new event type."""
        handler = AsyncMock()
        handler.__name__ = "handler"

        # Replace handlers for an event type that has no handlers yet
        dispatcher.replace_handlers(EventType.EXECUTION_TIMEOUT, [handler])

        current_handlers = dispatcher.get_handlers(EventType.EXECUTION_TIMEOUT)
        assert len(current_handlers) == 1
        assert handler in current_handlers

    def test_build_topic_mapping(self, dispatcher):
        """Test _build_topic_mapping builds correct mapping."""
        # The mapping should be built automatically in __init__
        # Just verify it has some expected mappings
        assert len(dispatcher._topic_event_types) > 0

        # ExecutionRequestedEvent should be mapped to EXECUTION_EVENTS topic
        execution_topic = str(KafkaTopic.EXECUTION_EVENTS)
        assert execution_topic in dispatcher._topic_event_types

        # Check that ExecutionRequestedEvent is in the set for this topic
        event_classes = dispatcher._topic_event_types[execution_topic]
        assert any(cls.__name__ == 'ExecutionRequestedEvent' for cls in event_classes)

    @pytest.mark.asyncio
    async def test_dispatch_concurrent_handlers(self, dispatcher):
        """Test that dispatch runs handlers concurrently."""
        call_order = []

        async def handler1(event: BaseEvent):
            call_order.append("handler1_start")
            await asyncio.sleep(0.01)
            call_order.append("handler1_end")

        async def handler2(event: BaseEvent):
            call_order.append("handler2_start")
            await asyncio.sleep(0.005)
            call_order.append("handler2_end")

        handler1.__name__ = "handler1"
        handler2.__name__ = "handler2"

        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, handler1)
        dispatcher.register_handler(EventType.EXECUTION_REQUESTED, handler2)

        event = make_execution_requested_event()
        await dispatcher.dispatch(event)

        # If they run concurrently, we should see interleaved starts before ends
        assert call_order[0] in ["handler1_start", "handler2_start"]
        assert call_order[1] in ["handler1_start", "handler2_start"]
        assert "handler1_start" in call_order
        assert "handler2_start" in call_order
        assert "handler1_end" in call_order
        assert "handler2_end" in call_order

    def test_get_metrics_empty(self, dispatcher):
        """Test get_metrics with no events processed."""
        metrics = dispatcher.get_metrics()
        assert metrics == {}

