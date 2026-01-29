import logging
from collections.abc import Awaitable, Callable

from app.domain.events.typed import DomainEvent
from app.domain.idempotency import KeyStrategy
from app.events.core.dispatcher import EventDispatcher, EventHandler
from app.services.idempotency.idempotency_manager import IdempotencyManager


class IdempotentEventHandler:
    """Wraps a single event handler with idempotency check-and-reserve logic."""

    def __init__(
        self,
        handler: Callable[[DomainEvent], Awaitable[None]],
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        fields: set[str] | None = None,
        ttl_seconds: int | None = None,
    ):
        self.handler = handler
        self.idempotency_manager = idempotency_manager
        self.logger = logger
        self.key_strategy = key_strategy
        self.fields = fields
        self.ttl_seconds = ttl_seconds
        self.__name__ = handler.__name__

    async def __call__(self, event: DomainEvent) -> None:
        """Process event with idempotency check."""
        self.logger.info(
            f"IdempotentEventHandler called for event {event.event_type}, "
            f"id={event.event_id}, handler={self.__name__}"
        )

        idempotency_result = await self.idempotency_manager.check_and_reserve(
            event=event,
            key_strategy=self.key_strategy,
            ttl_seconds=self.ttl_seconds,
            fields=self.fields,
        )

        if idempotency_result.is_duplicate:
            self.logger.info(
                f"Duplicate event detected: {event.event_type} ({event.event_id}), status: {idempotency_result.status}"
            )
            return

        try:
            await self.handler(event)
            await self.idempotency_manager.mark_completed(
                event=event, key_strategy=self.key_strategy, fields=self.fields
            )
        except Exception as e:
            await self.idempotency_manager.mark_failed(
                event=event, error=str(e), key_strategy=self.key_strategy, fields=self.fields
            )
            raise


class IdempotentEventDispatcher(EventDispatcher):
    """EventDispatcher that automatically wraps every handler with idempotency.

    Drop-in replacement for ``EventDispatcher`` — DI providers create this
    subclass for services that need idempotent event handling.
    """

    def __init__(
        self,
        logger: logging.Logger,
        idempotency_manager: IdempotencyManager,
        key_strategy: KeyStrategy = KeyStrategy.EVENT_BASED,
        ttl_seconds: int = 3600,
    ) -> None:
        super().__init__(logger=logger)
        self._idempotency_manager = idempotency_manager
        self._key_strategy = key_strategy
        self._ttl_seconds = ttl_seconds

    def _wrap_handler(self, handler: EventHandler) -> EventHandler:
        return IdempotentEventHandler(
            handler=handler,
            idempotency_manager=self._idempotency_manager,
            logger=self.logger,
            key_strategy=self._key_strategy,
            ttl_seconds=self._ttl_seconds,
        )
