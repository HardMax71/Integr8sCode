import logging
from typing import Awaitable, Callable

from app.domain.events.typed import DomainEvent

from .producer import UnifiedProducer


def create_dlq_error_handler(
    producer: UnifiedProducer, original_topic: str, logger: logging.Logger, max_retries: int = 3
) -> Callable[[Exception, DomainEvent], Awaitable[None]]:
    """Create an error handler that sends failed events to DLQ after max retries."""
    retry_counts: dict[str, int] = {}

    async def handle_error_with_dlq(error: Exception, event: DomainEvent) -> None:
        event_id = event.event_id or "unknown"
        retry_count = retry_counts.get(event_id, 0)
        retry_counts[event_id] = retry_count + 1
        logger.error(f"Error processing {event_id}: {error}. Retry {retry_count + 1}/{max_retries}", exc_info=True)
        if retry_count >= max_retries:
            logger.warning(f"Event {event_id} exceeded max retries. Sending to DLQ.")
            await producer.send_to_dlq(event, original_topic, error, retry_count)
            retry_counts.pop(event_id, None)

    return handle_error_with_dlq


def create_immediate_dlq_handler(
    producer: UnifiedProducer, original_topic: str, logger: logging.Logger
) -> Callable[[Exception, DomainEvent], Awaitable[None]]:
    """Create an error handler that immediately sends failed events to DLQ."""

    async def handle_error_immediate_dlq(error: Exception, event: DomainEvent) -> None:
        logger.error(f"Critical error processing {event.event_id}: {error}. Sending to DLQ.", exc_info=True)
        await producer.send_to_dlq(event, original_topic, error, 0)

    return handle_error_immediate_dlq
