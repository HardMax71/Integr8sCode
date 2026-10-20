from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import structlog
from dishka import AsyncContainer
from faststream import BaseMiddleware, StreamMessage

from app.db.docs import DLQMessageDocument
from app.dlq import DLQ_GROUP_HEADER, DLQ_RETRY_HEADER
from app.dlq.manager import DLQManager
from app.domain.events import DomainEventAdapter
from app.domain.idempotency import KeyStrategy
from app.services.idempotency import IdempotencyManager


# --8<-- [start:IdempotencyMiddleware]
class IdempotencyMiddleware(BaseMiddleware):
    """Runs a handler at most once per idempotency key while the key lives in Redis.

    The key is reserved before the handler runs, then marked completed when it returns
    or released when it raises, so a retry from the DLQ can run the handler again. A
    delivery whose key is already taken is skipped, so Kafka commits its offset without
    running the handler again.
    """

    def __init__(self, msg: Any, /, *, key_strategy: KeyStrategy, ttl_seconds: int, **kwargs: Any) -> None:
        super().__init__(msg, **kwargs)
        self.key_strategy = key_strategy
        self.ttl_seconds = ttl_seconds

    async def consume_scope(
        self,
        call_next: Callable[[StreamMessage[Any]], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        # The broker-level Dishka middleware wraps this one and opens the request container
        container: AsyncContainer = self.context.get_local("dishka")
        idem = await container.get(IdempotencyManager)
        event = DomainEventAdapter.validate_python(await msg.decode())

        reservation = await idem.check_and_reserve(
            event=event, key_strategy=self.key_strategy, ttl_seconds=self.ttl_seconds
        )
        if reservation.is_duplicate:
            logger = await container.get(structlog.stdlib.BoundLogger)
            logger.info("Duplicate event", event_type=event.event_type, event_id=event.event_id)
            return None

        try:
            result = await call_next(msg)
        except Exception:
            await idem.release(event=event, key_strategy=self.key_strategy)
            raise
        await idem.mark_completed(event=event, key_strategy=self.key_strategy)
        return result


# --8<-- [end:IdempotencyMiddleware]


def idempotent(key_strategy: KeyStrategy, ttl_seconds: int) -> Callable[..., IdempotencyMiddleware]:
    """Build the middleware factory a ``KafkaRouter`` takes, fixing the key strategy and TTL."""
    return partial(IdempotencyMiddleware, key_strategy=key_strategy, ttl_seconds=ttl_seconds)


# --8<-- [start:DeadLetterMiddleware]
class DeadLetterMiddleware(BaseMiddleware):
    """Saves an event whose handler raised to the DLQ, for the dlq-processor to retry in this consumer group.

    The error still propagates, so FastStream logs it and the telemetry middleware counts it.
    """

    async def consume_scope(
        self,
        call_next: Callable[[StreamMessage[Any]], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        try:
            return await call_next(msg)
        except Exception as e:
            container: AsyncContainer = self.context.get_local("dishka")
            manager = await container.get(DLQManager)
            event = DomainEventAdapter.validate_python(await msg.decode())
            await manager.handle_message(
                DLQMessageDocument(
                    event=event,
                    original_topic=msg.raw_message.topic,
                    consumer_group=self.context.get_local("handler_").group_id,
                    error=str(e),
                    retry_count=int(msg.headers.get(DLQ_RETRY_HEADER, 0)),
                    producer_id=event.metadata.service_name,
                )
            )
            raise


class RetryTargetMiddleware(BaseMiddleware):
    """Skips a DLQ retry that's addressed to another consumer group."""

    async def consume_scope(
        self,
        call_next: Callable[[StreamMessage[Any]], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        target = msg.headers.get(DLQ_GROUP_HEADER)
        if target and target != self.context.get_local("handler_").group_id:
            return None
        return await call_next(msg)


# --8<-- [end:DeadLetterMiddleware]
