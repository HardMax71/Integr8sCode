import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeAlias, TypeVar

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent

T = TypeVar("T", bound=DomainEvent)
EventHandler: TypeAlias = Callable[[DomainEvent], Awaitable[None]]


class EventDispatcher:
    """
    Type-safe event dispatcher with automatic routing.

    This dispatcher eliminates the need for manual if/elif routing by maintaining
    a direct mapping from event types to their handlers.

    Subclasses may override ``_wrap_handler`` to intercept handler registration
    (e.g. ``IdempotentEventDispatcher`` adds idempotency protection).
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

        # Map event types to their handlers
        self._handlers: dict[EventType, list[Callable[[DomainEvent], Awaitable[None]]]] = defaultdict(list)

    def _wrap_handler(self, handler: EventHandler) -> EventHandler:
        """Hook for subclasses to wrap handlers at registration time."""
        return handler

    def register(
        self, event_type: EventType
    ) -> Callable[[Callable[[T], Awaitable[None]]], Callable[[T], Awaitable[None]]]:
        """
        Decorator for registering type-safe event handlers.

        Generic over T (any DomainEvent subtype) - accepts handlers with specific
        event types while preserving their type signature for callers.

        Usage:
            @dispatcher.register(EventType.EXECUTION_REQUESTED)
            async def handle_execution(event: ExecutionRequestedEvent) -> None:
                # Handler logic here - event is properly typed
        """

        def decorator(handler: Callable[[T], Awaitable[None]]) -> Callable[[T], Awaitable[None]]:
            self.logger.info(f"Registering handler '{handler.__name__}' for event type '{event_type}'")
            # Safe: dispatch() routes by event_type, guaranteeing correct types at runtime
            self._handlers[event_type].append(self._wrap_handler(handler))  # type: ignore[arg-type]
            return handler

        return decorator

    def register_handler(self, event_type: EventType, handler: EventHandler) -> None:
        """
        Direct registration method for handlers.

        Args:
            event_type: The event type this handler processes
            handler: The async handler function
        """
        self.logger.info(f"Registering handler '{handler.__name__}' for event type '{event_type}'")
        self._handlers[event_type].append(self._wrap_handler(handler))

    async def dispatch(self, event: DomainEvent) -> None:
        """
        Dispatch an event to all registered handlers for its type.

        Args:
            event: The event to dispatch
        """
        event_type = event.event_type
        handlers = self._handlers.get(event_type, [])
        self.logger.debug(f"Dispatcher has {len(self._handlers)} event types registered")
        self.logger.debug(
            f"For event type {event_type}, found {len(handlers)} handlers: {[h.__class__.__name__ for h in handlers]}"
        )

        if not handlers:
            self.logger.debug(f"No handlers registered for event type {event_type}")
            return

        self.logger.debug(f"Dispatching {event_type} to {len(handlers)} handler(s)")

        # Run handlers concurrently for better performance
        tasks = [self._execute_handler(handler, event) for handler in handlers]
        await asyncio.gather(*tasks)

    async def _execute_handler(self, handler: EventHandler, event: DomainEvent) -> None:
        """
        Execute a single handler with error handling.

        Args:
            handler: The handler function
            event: The event to process
        """
        try:
            self.logger.debug(f"Executing handler {handler.__class__.__name__} for event {event.event_id}")
            await handler(event)
            self.logger.debug(f"Handler {handler.__class__.__name__} completed")
        except Exception as e:
            self.logger.error(
                f"Handler '{handler.__class__.__name__}' failed for event {event.event_id}: {e}", exc_info=True
            )
            raise

