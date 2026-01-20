"""Idempotent event processing middleware"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.events.core import EventDispatcher, UnifiedConsumer
from app.services.idempotency.idempotency_manager import IdempotencyManager


class IdempotentEventHandler:
    """Wrapper for event handlers with idempotency support."""

    def __init__(
        self,
        handler: Callable[[DomainEvent], Awaitable[None]],
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
        key_strategy: str = "event_based",
        custom_key_func: Callable[[DomainEvent], str] | None = None,
        fields: set[str] | None = None,
        ttl_seconds: int | None = None,
        on_duplicate: Callable[[DomainEvent, Any], Any] | None = None,
    ):
        self.handler = handler
        self.idempotency_manager = idempotency_manager
        self.logger = logger
        self.key_strategy = key_strategy
        self.custom_key_func = custom_key_func
        self.fields = fields
        self.ttl_seconds = ttl_seconds
        self.on_duplicate = on_duplicate

    async def __call__(self, event: DomainEvent) -> None:
        custom_key = self.custom_key_func(event) if self.key_strategy == "custom" and self.custom_key_func else None

        result = await self.idempotency_manager.check_and_reserve(
            event=event,
            key_strategy=self.key_strategy,
            custom_key=custom_key,
            ttl_seconds=self.ttl_seconds,
            fields=self.fields,
        )

        if result.is_duplicate:
            self.logger.info(f"Duplicate event: {event.event_type} ({event.event_id})")
            if self.on_duplicate:
                if asyncio.iscoroutinefunction(self.on_duplicate):
                    await self.on_duplicate(event, result)
                else:
                    await asyncio.to_thread(self.on_duplicate, event, result)
            return

        try:
            await self.handler(event)
            await self.idempotency_manager.mark_completed(
                event=event, key_strategy=self.key_strategy, custom_key=custom_key, fields=self.fields
            )
        except Exception as e:
            await self.idempotency_manager.mark_failed(
                event=event, error=str(e), key_strategy=self.key_strategy, custom_key=custom_key, fields=self.fields
            )
            raise


class IdempotentConsumerWrapper:
    """Wrapper for UnifiedConsumer with automatic idempotency.

    Usage:
        dispatcher = EventDispatcher()
        dispatcher.register(EventType.FOO, handle_foo)

        consumer = UnifiedConsumer(..., dispatcher=dispatcher)
        wrapper = IdempotentConsumerWrapper(consumer, dispatcher, idempotency_manager, ...)
        await wrapper.run()  # Handlers are wrapped with idempotency, then consumer runs
    """

    def __init__(
        self,
        consumer: UnifiedConsumer,
        dispatcher: EventDispatcher,
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
        default_key_strategy: str = "event_based",
        default_ttl_seconds: int = 3600,
        enable_for_all_handlers: bool = True,
    ):
        self._consumer = consumer
        self._dispatcher = dispatcher
        self._idempotency_manager = idempotency_manager
        self._logger = logger
        self._default_key_strategy = default_key_strategy
        self._default_ttl_seconds = default_ttl_seconds
        self._enable_for_all_handlers = enable_for_all_handlers

    async def run(self) -> None:
        """Wrap handlers with idempotency, then run consumer."""
        if self._enable_for_all_handlers:
            self._wrap_handlers()
        self._logger.info("IdempotentConsumerWrapper running")
        await self._consumer.run()

    def _wrap_handlers(self) -> None:
        """Wrap all registered handlers with idempotency."""
        original_handlers = self._dispatcher.get_all_handlers()

        for event_type, handlers in original_handlers.items():
            wrapped: list[Callable[[DomainEvent], Awaitable[None]]] = [
                IdempotentEventHandler(
                    handler=h,
                    idempotency_manager=self._idempotency_manager,
                    logger=self._logger,
                    key_strategy=self._default_key_strategy,
                    ttl_seconds=self._default_ttl_seconds,
                )
                for h in handlers
            ]
            self._dispatcher.replace_handlers(event_type, wrapped)

    def register_idempotent_handler(
        self,
        event_type: EventType,
        handler: Callable[[DomainEvent], Awaitable[None]],
        key_strategy: str | None = None,
        custom_key_func: Callable[[DomainEvent], str] | None = None,
        fields: set[str] | None = None,
        ttl_seconds: int | None = None,
        on_duplicate: Callable[[DomainEvent, Any], Any] | None = None,
    ) -> None:
        """Register an idempotent handler for an event type."""
        wrapped = IdempotentEventHandler(
            handler=handler,
            idempotency_manager=self._idempotency_manager,
            logger=self._logger,
            key_strategy=key_strategy or self._default_key_strategy,
            custom_key_func=custom_key_func,
            fields=fields,
            ttl_seconds=ttl_seconds or self._default_ttl_seconds,
            on_duplicate=on_duplicate,
        )
        self._dispatcher.register(event_type)(wrapped)
