"""FastStream middleware for idempotent event processing.

Uses Dishka's request-scoped container to resolve dependencies per-message.
Must be added to broker AFTER setup_dishka() is called.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from faststream import BaseMiddleware
from faststream.message import StreamMessage

from app.domain.events.typed import DomainEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.idempotency_manager import IdempotencyManager


class IdempotencyMiddleware(BaseMiddleware):
    """
    FastStream middleware providing idempotent message processing.

    Resolves IdempotencyManager and SchemaRegistryManager from Dishka's
    request-scoped container (available via context after DishkaMiddleware runs).

    Flow:
    1. DishkaMiddleware.consume_scope creates request container in context
    2. This middleware's consume_scope resolves dependencies from container
    3. Decodes Avro message and checks idempotency
    4. Skips handler if duplicate, otherwise proceeds and marks result
    """

    async def consume_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        """Check idempotency before processing, mark completed/failed after."""
        # Get Dishka request container from context (set by DishkaMiddleware)
        container = self.context.get_local("dishka")
        if container is None:
            # Dishka not set up or middleware order wrong - skip idempotency
            return await call_next(msg)

        # Resolve dependencies from request-scoped container
        try:
            idempotency = await container.get(IdempotencyManager)
            schema_registry = await container.get(SchemaRegistryManager)
        except Exception:
            # Dependencies not available - skip idempotency
            return await call_next(msg)

        # Decode message to get event for idempotency check
        body = msg.body
        if not isinstance(body, bytes):
            # Not Avro bytes - skip idempotency
            return await call_next(msg)

        try:
            event: DomainEvent = await schema_registry.deserialize_event(body, "idempotency")
        except Exception:
            # Failed to decode - let handler deal with it
            return await call_next(msg)

        # Check idempotency
        result = await idempotency.check_and_reserve(
            event=event,
            key_strategy="event_based",
        )

        if result.is_duplicate:
            # Skip handler for duplicates
            return None

        # Not a duplicate - proceed with processing
        try:
            handler_result = await call_next(msg)
            await idempotency.mark_completed(event=event, key_strategy="event_based")
            return handler_result
        except Exception as e:
            await idempotency.mark_failed(event=event, error=str(e), key_strategy="event_based")
            raise
