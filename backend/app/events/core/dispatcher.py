import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.logging import logger
from app.domain.enums.events import EventType
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.mappings import get_event_class_for_type

T = TypeVar("T", bound=BaseEvent)


class EventDispatcher:
    """
    Type-safe event dispatcher with automatic routing.

    This dispatcher eliminates the need for manual if/elif routing by maintaining
    a direct mapping from event types to their handlers.
    """

    def __init__(self) -> None:
        # Map event types to their handlers
        self._handlers: dict[EventType, list[Callable[[BaseEvent], Awaitable[None]]]] = defaultdict(list)

        # Map topics to event types that can appear on them
        self._topic_event_types: dict[str, set[type[BaseEvent]]] = defaultdict(set)

        # Metrics per event type
        self._event_metrics: dict[EventType, dict[str, int]] = defaultdict(
            lambda: {"processed": 0, "failed": 0, "skipped": 0}
        )

        # Build topic->event type mapping from schema
        self._build_topic_mapping()

    def _build_topic_mapping(self) -> None:
        """Build mapping of topics to event types based on event classes."""
        for event_class in BaseEvent.__subclasses__():
            if hasattr(event_class, "topic"):
                topic = str(event_class.topic)
                self._topic_event_types[topic].add(event_class)
                logger.debug(f"Mapped {event_class.__name__} to topic {topic}")

    def register(self, event_type: EventType) -> Callable:
        """
        Decorator for registering type-safe event handlers.

        Usage:
            @dispatcher.register(EventType.EXECUTION_REQUESTED)
            async def handle_execution(event: ExecutionRequestedEvent) -> None:
                # Handler logic here
        """

        def decorator(handler: Callable[[BaseEvent], Awaitable[None]]) -> Callable:
            logger.info(f"Registering handler '{handler.__name__}' for event type '{event_type.value}'")
            self._handlers[event_type].append(handler)
            return handler

        return decorator

    def register_handler(self, event_type: EventType, handler: Callable[[BaseEvent], Awaitable[None]]) -> None:
        """
        Direct registration method for handlers.

        Args:
            event_type: The event type this handler processes
            handler: The async handler function
        """
        logger.info(f"Registering handler '{handler.__name__}' for event type '{event_type.value}'")
        self._handlers[event_type].append(handler)

    def remove_handler(self, event_type: EventType, handler: Callable[[BaseEvent], Awaitable[None]]) -> bool:
        """
        Remove a specific handler for an event type.

        Args:
            event_type: The event type to remove handler from
            handler: The handler function to remove

        Returns:
            True if handler was found and removed, False otherwise
        """
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
            logger.info(f"Removed handler '{handler.__name__}' for event type '{event_type.value}'")
            # Clean up empty lists
            if not self._handlers[event_type]:
                del self._handlers[event_type]
            return True
        return False

    async def dispatch(self, event: BaseEvent) -> None:
        """
        Dispatch an event to all registered handlers for its type.

        Args:
            event: The event to dispatch
        """
        event_type = event.event_type
        handlers = self._handlers.get(event_type, [])
        logger.debug(f"Dispatcher has {len(self._handlers)} event types registered")
        logger.debug(
            f"For event type {event_type}, found {len(handlers)} handlers: {[h.__class__.__name__ for h in handlers]}"
        )

        if not handlers:
            self._event_metrics[event_type]["skipped"] += 1
            logger.debug(f"No handlers registered for event type {event_type.value}")
            return

        logger.debug(f"Dispatching {event_type.value} to {len(handlers)} handler(s)")

        # Run handlers concurrently for better performance
        tasks = []
        for handler in handlers:
            tasks.append(self._execute_handler(handler, event))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes and failures
        for result in results:
            if isinstance(result, Exception):
                self._event_metrics[event_type]["failed"] += 1
            else:
                self._event_metrics[event_type]["processed"] += 1

    async def _execute_handler(self, handler: Callable, event: BaseEvent) -> None:
        """
        Execute a single handler with error handling.

        Args:
            handler: The handler function
            event: The event to process
        """
        try:
            logger.debug(f"Executing handler {handler.__class__.__name__} for event {event.event_id}")
            result = await handler(event)
            logger.debug(f"Handler {handler.__class__.__name__} completed, result: {result}")
        except Exception as e:
            logger.error(
                f"Handler '{handler.__class__.__name__}' failed for event {event.event_id}: {e}", exc_info=True
            )
            raise

    def get_topics_for_registered_handlers(self) -> set[str]:
        """
        Get all topics that have registered handlers.

        Returns:
            Set of topic names that should be subscribed to
        """
        topics = set()
        for event_type in self._handlers.keys():
            # Find event class for this type
            event_class = get_event_class_for_type(event_type)
            if event_class and hasattr(event_class, "topic"):
                topics.add(str(event_class.topic))
        return topics

    def get_metrics(self) -> dict[str, dict[str, int]]:
        """Get processing metrics for all event types."""
        return {event_type.value: metrics for event_type, metrics in self._event_metrics.items()}

    def clear_handlers(self) -> None:
        """Clear all registered handlers (useful for testing)."""
        self._handlers.clear()
        logger.info("All event handlers cleared")

    def get_handlers(self, event_type: EventType) -> list[Callable[[BaseEvent], Awaitable[None]]]:
        """Get all handlers for a specific event type."""
        return self._handlers.get(event_type, []).copy()

    def get_all_handlers(self) -> dict[EventType, list[Callable[[BaseEvent], Awaitable[None]]]]:
        """Get all registered handlers (returns a copy)."""
        return {k: v.copy() for k, v in self._handlers.items()}

    def replace_handlers(self, event_type: EventType, handlers: list[Callable[[BaseEvent], Awaitable[None]]]) -> None:
        """Replace all handlers for a specific event type."""
        self._handlers[event_type] = handlers
