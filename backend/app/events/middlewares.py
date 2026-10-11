from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import structlog
from dishka import AsyncContainer
from faststream import BaseMiddleware, StreamMessage

from app.domain.events import DomainEventAdapter
from app.domain.idempotency import KeyStrategy
from app.services.idempotency import IdempotencyManager


# --8<-- [start:IdempotencyMiddleware]
class IdempotencyMiddleware(BaseMiddleware):
    """Runs a handler at most once per idempotency key while the key lives in Redis.

    The key is reserved before the handler runs, then marked completed when it returns
    or failed when it raises. A delivery whose key is already taken is skipped, so
    Kafka commits its offset without running the handler again.
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
        except Exception as e:
            await idem.mark_failed(event=event, error=str(e), key_strategy=self.key_strategy)
            raise
        await idem.mark_completed(event=event, key_strategy=self.key_strategy)
        return result


# --8<-- [end:IdempotencyMiddleware]


def idempotent(key_strategy: KeyStrategy, ttl_seconds: int) -> Callable[..., IdempotencyMiddleware]:
    """Build the middleware factory a ``KafkaRouter`` takes, fixing the key strategy and TTL."""
    return partial(IdempotencyMiddleware, key_strategy=key_strategy, ttl_seconds=ttl_seconds)
