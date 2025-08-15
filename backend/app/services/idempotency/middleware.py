"""Idempotent event processing middleware"""

import asyncio
import functools
import time
from typing import Any, Callable, Dict, Optional, Set

from aiokafka.structs import ConsumerRecord

from app.core.logging import logger
from app.core.metrics import Counter, Histogram
from app.events.core.consumer import UnifiedConsumer
from app.schemas_avro.event_schemas import BaseEvent
from app.services.idempotency.idempotency_manager import IdempotencyManager

# Metrics
IDEMPOTENT_EVENTS_PROCESSED = Counter(
    "idempotent_events_processed_total",
    "Total number of events processed with idempotency",
    ["event_type", "result"]
)

IDEMPOTENT_PROCESSING_DURATION = Histogram(
    "idempotent_processing_duration_seconds",
    "Time taken to process events with idempotency",
    ["event_type"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0]
)


class IdempotentEventHandler:
    """Wrapper for event handlers with idempotency support"""

    def __init__(
            self,
            handler: Callable,
            idempotency_manager: IdempotencyManager,
            key_strategy: str = "event_based",
            custom_key_func: Optional[Callable[[BaseEvent], str]] = None,
            fields: Optional[Set[str]] = None,
            ttl_seconds: Optional[int] = None,
            cache_result: bool = True,
            on_duplicate: Optional[Callable] = None
    ):
        self.handler = handler
        self.idempotency_manager = idempotency_manager
        self.key_strategy = key_strategy
        self.custom_key_func = custom_key_func
        self.fields = fields
        self.ttl_seconds = ttl_seconds
        self.cache_result = cache_result
        self.on_duplicate = on_duplicate

    async def __call__(self, event: BaseEvent, record: Optional[ConsumerRecord] = None) -> Any:
        """Process event with idempotency check"""
        start_time = time.time()

        # Generate custom key if function provided
        custom_key = None
        if self.key_strategy == "custom" and self.custom_key_func:
            custom_key = self.custom_key_func(event)

        # Check idempotency
        idempotency_result = await self.idempotency_manager.check_and_reserve(
            event=event,
            key_strategy=self.key_strategy,
            custom_key=custom_key,
            ttl_seconds=self.ttl_seconds,
            fields=self.fields
        )

        if idempotency_result.is_duplicate:
            # Handle duplicate
            IDEMPOTENT_EVENTS_PROCESSED.labels(
                event_type=event.event_type,
                result="duplicate"
            ).inc()

            logger.info(
                f"Duplicate event detected: {event.event_type} ({event.event_id}), "
                f"status: {idempotency_result.status}"
            )

            # Call duplicate handler if provided
            if self.on_duplicate:
                if asyncio.iscoroutinefunction(self.on_duplicate):
                    await self.on_duplicate(event, idempotency_result)
                else:
                    await asyncio.to_thread(self.on_duplicate, event, idempotency_result)

            # Return cached result if available
            if idempotency_result.result is not None:
                return idempotency_result.result

            # If still processing or no result cached, return None
            return None

        # Not a duplicate, process the event
        try:
            # Call the actual handler
            if asyncio.iscoroutinefunction(self.handler):
                result = await self.handler(event, record) if record else await self.handler(event)
            else:
                result = await asyncio.to_thread(
                    self.handler, event, record
                ) if record else await asyncio.to_thread(self.handler, event)

            # Mark as completed
            if self.idempotency_manager:
                await self.idempotency_manager.mark_completed(
                event=event,
                result=result if self.cache_result else None,
                key_strategy=self.key_strategy,
                custom_key=custom_key,
                fields=self.fields
            )

            # Update metrics
            duration = time.time() - start_time
            IDEMPOTENT_PROCESSING_DURATION.labels(
                event_type=event.event_type
            ).observe(duration)

            IDEMPOTENT_EVENTS_PROCESSED.labels(
                event_type=event.event_type,
                result="processed"
            ).inc()

            return result

        except Exception as e:
            # Mark as failed
            await self.idempotency_manager.mark_failed(
                event=event,
                error=str(e),
                key_strategy=self.key_strategy,
                custom_key=custom_key,
                fields=self.fields
            )

            IDEMPOTENT_EVENTS_PROCESSED.labels(
                event_type=event.event_type,
                result="failed"
            ).inc()

            raise


def idempotent_handler(
        idempotency_manager: IdempotencyManager,
        key_strategy: str = "event_based",
        custom_key_func: Optional[Callable[[BaseEvent], str]] = None,
        fields: Optional[Set[str]] = None,
        ttl_seconds: Optional[int] = None,
        cache_result: bool = True,
        on_duplicate: Optional[Callable] = None
) -> Callable[[Callable], Callable]:
    """Decorator for making event handlers idempotent"""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(event: BaseEvent, *args: Any, **kwargs: Any) -> Any:
            handler = IdempotentEventHandler(
                handler=func,
                idempotency_manager=idempotency_manager,
                key_strategy=key_strategy,
                custom_key_func=custom_key_func,
                fields=fields,
                ttl_seconds=ttl_seconds,
                cache_result=cache_result,
                on_duplicate=on_duplicate
            )
            return await handler(event, *args, **kwargs)

        return wrapper

    return decorator


class IdempotentConsumerWrapper:
    """Wrapper for Kafka consumer with automatic idempotency"""

    def __init__(
            self,
            consumer: UnifiedConsumer,
            idempotency_manager: IdempotencyManager,
            default_key_strategy: str = "event_based",
            default_ttl_seconds: int = 3600,
            enable_for_all_handlers: bool = True
    ):
        self.consumer = consumer
        self.idempotency_manager = idempotency_manager
        self.default_key_strategy = default_key_strategy
        self.default_ttl_seconds = default_ttl_seconds
        self.enable_for_all_handlers = enable_for_all_handlers
        self._original_handlers: Dict[str, list] = {}

    def make_handlers_idempotent(self) -> None:
        """Wrap all registered handlers with idempotency"""
        if not self.enable_for_all_handlers:
            return

        # Store original handlers
        self._original_handlers = self.consumer._event_handlers.copy()

        # Wrap each handler
        for event_type, handlers in self.consumer._event_handlers.items():
            wrapped_handlers = []
            for handler in handlers:
                # Skip if already wrapped
                if isinstance(handler, IdempotentEventHandler):
                    wrapped_handlers.append(handler)
                else:
                    # Wrap with idempotency
                    wrapped = IdempotentEventHandler(
                        handler=handler,
                        idempotency_manager=self.idempotency_manager,
                        key_strategy=self.default_key_strategy,
                        ttl_seconds=self.default_ttl_seconds
                    )
                    wrapped_handlers.append(wrapped)

            # Cast to the expected type
            self.consumer._event_handlers[event_type] = wrapped_handlers  # type: ignore[assignment]

    def subscribe_idempotent_handler(
            self,
            event_type: str,
            handler: Callable,
            key_strategy: Optional[str] = None,
            custom_key_func: Optional[Callable[[BaseEvent], str]] = None,
            fields: Optional[Set[str]] = None,
            ttl_seconds: Optional[int] = None,
            cache_result: bool = True,
            on_duplicate: Optional[Callable] = None
    ) -> None:
        """Subscribe an idempotent handler for specific event type"""
        # Create the idempotent handler wrapper
        idempotent_wrapper = IdempotentEventHandler(
            handler=handler,
            idempotency_manager=self.idempotency_manager,
            key_strategy=key_strategy or self.default_key_strategy,
            custom_key_func=custom_key_func,
            fields=fields,
            ttl_seconds=ttl_seconds or self.default_ttl_seconds,
            cache_result=cache_result,
            on_duplicate=on_duplicate
        )

        # Create a handler that requires typed events
        async def async_handler(event: BaseEvent, record: ConsumerRecord) -> Any:
            # Consumer should always provide typed events
            if not isinstance(event, BaseEvent):
                raise TypeError(f"Expected BaseEvent, got {type(event).__name__}")
            return await idempotent_wrapper(event, record)

        self.consumer.register_handler(event_type, async_handler)

    async def start(self) -> None:
        """Start the consumer with idempotency"""
        # Make handlers idempotent before starting
        self.make_handlers_idempotent()

        # Start the consumer
        await self.consumer.start()

    async def stop(self) -> None:
        """Stop the consumer"""
        await self.consumer.stop()

    # Delegate other methods to the wrapped consumer
    def __getattr__(self, name: str) -> Any:
        return getattr(self.consumer, name)
