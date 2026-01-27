"""Idempotent event processing middleware"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Set

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.domain.idempotency import KeyStrategy
from app.events.core import EventDispatcher, UnifiedConsumer
from app.services.idempotency.idempotency_manager import IdempotencyManager


class IdempotentEventHandler:
    """Wrapper for event handlers with idempotency support"""

    def __init__(
        self,
        handler: Callable[[DomainEvent], Awaitable[None]],
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        custom_key_func: Callable[[DomainEvent], str] | None = None,
        fields: Set[str] | None = None,
        ttl_seconds: int | None = None,
        cache_result: bool = True,
        on_duplicate: Callable[[DomainEvent, Any], Any] | None = None,
    ):
        self.handler = handler
        self.idempotency_manager = idempotency_manager
        self.logger = logger
        self.key_strategy = key_strategy
        self.custom_key_func = custom_key_func
        self.fields = fields
        self.ttl_seconds = ttl_seconds
        self.cache_result = cache_result
        self.on_duplicate = on_duplicate

    async def __call__(self, event: DomainEvent) -> None:
        """Process event with idempotency check"""
        self.logger.info(
            f"IdempotentEventHandler called for event {event.event_type}, "
            f"id={event.event_id}, handler={self.handler.__name__}"
        )
        # Generate custom key if function provided
        custom_key = None
        if self.key_strategy == KeyStrategy.CUSTOM and self.custom_key_func:
            custom_key = self.custom_key_func(event)

        # Check idempotency
        idempotency_result = await self.idempotency_manager.check_and_reserve(
            event=event,
            key_strategy=self.key_strategy,
            custom_key=custom_key,
            ttl_seconds=self.ttl_seconds,
            fields=self.fields,
        )

        if idempotency_result.is_duplicate:
            # Handle duplicate
            self.logger.info(
                f"Duplicate event detected: {event.event_type} ({event.event_id}), status: {idempotency_result.status}"
            )

            # Call duplicate handler if provided
            if self.on_duplicate:
                if asyncio.iscoroutinefunction(self.on_duplicate):
                    await self.on_duplicate(event, idempotency_result)
                else:
                    await asyncio.to_thread(self.on_duplicate, event, idempotency_result)

            # For duplicate, just return without error
            return

        # Not a duplicate, process the event
        try:
            # Call the actual handler - it returns None
            await self.handler(event)

            # Mark as completed
            await self.idempotency_manager.mark_completed(
                event=event, key_strategy=self.key_strategy, custom_key=custom_key, fields=self.fields
            )

        except Exception as e:
            # Mark as failed
            await self.idempotency_manager.mark_failed(
                event=event, error=str(e), key_strategy=self.key_strategy, custom_key=custom_key, fields=self.fields
            )
            raise


def idempotent_handler(
    idempotency_manager: IdempotencyManager,
    logger: logging.Logger,
    key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
    custom_key_func: Callable[[DomainEvent], str] | None = None,
    fields: Set[str] | None = None,
    ttl_seconds: int | None = None,
    cache_result: bool = True,
    on_duplicate: Callable[[DomainEvent, Any], Any] | None = None,
) -> Callable[[Callable[[DomainEvent], Awaitable[None]]], Callable[[DomainEvent], Awaitable[None]]]:
    """Decorator for making event handlers idempotent"""

    def decorator(func: Callable[[DomainEvent], Awaitable[None]]) -> Callable[[DomainEvent], Awaitable[None]]:
        handler = IdempotentEventHandler(
            handler=func,
            idempotency_manager=idempotency_manager,
            logger=logger,
            key_strategy=key_strategy,
            custom_key_func=custom_key_func,
            fields=fields,
            ttl_seconds=ttl_seconds,
            cache_result=cache_result,
            on_duplicate=on_duplicate,
        )
        return handler  # IdempotentEventHandler is already callable with the right signature

    return decorator


class IdempotentConsumerWrapper:
    """Wrapper for Kafka consumer with automatic idempotency"""

    def __init__(
        self,
        consumer: UnifiedConsumer,
        idempotency_manager: IdempotencyManager,
        dispatcher: EventDispatcher,
        logger: logging.Logger,
        default_key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        default_ttl_seconds: int = 3600,
        enable_for_all_handlers: bool = True,
    ):
        self.consumer = consumer
        self.idempotency_manager = idempotency_manager
        self.dispatcher = dispatcher
        self.logger = logger
        self.default_key_strategy = default_key_strategy
        self.default_ttl_seconds = default_ttl_seconds
        self._original_handlers: Dict[EventType, list[Callable[[DomainEvent], Awaitable[None]]]] = {}

        if enable_for_all_handlers:
            self._wrap_handlers()

    def _wrap_handlers(self) -> None:
        """Wrap all registered handlers with idempotency."""
        if not self.dispatcher:
            self.logger.warning("No dispatcher available for handler wrapping")
            return

        self._original_handlers = self.dispatcher.get_all_handlers()
        self.logger.debug(f"Wrapping {len(self._original_handlers)} event types with idempotency")

        # Wrap each handler
        for event_type, handlers in self._original_handlers.items():
            wrapped_handlers: list[Callable[[DomainEvent], Awaitable[None]]] = []
            for handler in handlers:
                # Wrap with idempotency - IdempotentEventHandler is callable with the right signature
                wrapped = IdempotentEventHandler(
                    handler=handler,
                    idempotency_manager=self.idempotency_manager,
                    logger=self.logger,
                    key_strategy=self.default_key_strategy,
                    ttl_seconds=self.default_ttl_seconds,
                )
                wrapped_handlers.append(wrapped)

            self.dispatcher.replace_handlers(event_type, wrapped_handlers)

    def subscribe_idempotent_handler(
        self,
        event_type: str,
        handler: Callable[[DomainEvent], Awaitable[None]],
        key_strategy: KeyStrategy | None = None,
        custom_key_func: Callable[[DomainEvent], str] | None = None,
        fields: Set[str] | None = None,
        ttl_seconds: int | None = None,
        cache_result: bool = True,
        on_duplicate: Callable[[DomainEvent, Any], Any] | None = None,
    ) -> None:
        """Subscribe an idempotent handler for specific event type"""
        # Create the idempotent handler wrapper
        idempotent_wrapper = IdempotentEventHandler(
            handler=handler,
            idempotency_manager=self.idempotency_manager,
            logger=self.logger,
            key_strategy=key_strategy or self.default_key_strategy,
            custom_key_func=custom_key_func,
            fields=fields,
            ttl_seconds=ttl_seconds or self.default_ttl_seconds,
            cache_result=cache_result,
            on_duplicate=on_duplicate,
        )

        # Create an async handler that processes the message
        async def async_handler(message: Any) -> Any:
            self.logger.info(f"IDEMPOTENT HANDLER CALLED for {event_type}")

            # Extract event from confluent-kafka Message
            if not hasattr(message, "value"):
                self.logger.error(f"Received non-Message object for {event_type}: {type(message)}")
                return None

            # Debug log to check message details
            self.logger.info(
                f"Handler for {event_type} - Message type: {type(message)}, "
                f"has key: {hasattr(message, 'key')}, "
                f"has topic: {hasattr(message, 'topic')}"
            )

            raw_value = message.value

            # Debug the raw value
            self.logger.info(f"Raw value extracted: {raw_value[:100] if raw_value else 'None or empty'}")

            # Handle tombstone messages (null value for log compaction)
            if raw_value is None:
                self.logger.warning(f"Received empty message for {event_type} - tombstone or consumed value")
                return None

            # Handle empty messages
            if not raw_value:
                self.logger.warning(f"Received empty message for {event_type} - empty bytes")
                return None

            try:
                # Deserialize using schema registry if available
                event = await self.consumer._schema_registry.deserialize_event(raw_value, message.topic)
                if not event:
                    self.logger.error(f"Failed to deserialize event for {event_type}")
                    return None

                # Call the idempotent wrapper directly in async context
                await idempotent_wrapper(event)

                self.logger.debug(f"Successfully processed {event_type} event: {event.event_id}")
                return None
            except Exception as e:
                self.logger.error(f"Failed to process message for {event_type}: {e}", exc_info=True)
                raise

        # Register with the dispatcher if available
        if self.dispatcher:
            # Create wrapper for EventDispatcher
            async def dispatch_handler(event: DomainEvent) -> None:
                await idempotent_wrapper(event)

            self.dispatcher.register(EventType(event_type))(dispatch_handler)
        else:
            # Fallback to direct consumer registration if no dispatcher
            self.logger.error(f"No EventDispatcher available for registering idempotent handler for {event_type}")
