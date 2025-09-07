from typing import Awaitable, Callable

from app.core.logging import logger
from app.events.core.producer import UnifiedProducer
from app.infrastructure.kafka.events.base import BaseEvent


def create_dlq_error_handler(
        producer: UnifiedProducer,
        original_topic: str,
        max_retries: int = 3
) -> Callable[[Exception, BaseEvent], Awaitable[None]]:
    """
    Create an error handler that sends failed events to DLQ.
    
    Args:
        producer: The Kafka producer to use for sending to DLQ
        original_topic: The topic where the event originally failed
        max_retries: Maximum number of retries before sending to DLQ
        
    Returns:
        An async error handler function suitable for UnifiedConsumer.register_error_callback
    """
    # Track retry counts per event ID
    retry_counts: dict[str, int] = {}

    async def handle_error_with_dlq(error: Exception, event: BaseEvent) -> None:
        """
        Handle processing errors by sending to DLQ after max retries.
        
        Args:
            error: The exception that occurred
            event: The event that failed processing
        """
        event_id = event.event_id or "unknown"

        # Track retry count
        retry_count = retry_counts.get(event_id, 0)
        retry_counts[event_id] = retry_count + 1

        logger.error(
            f"Error processing event {event_id} ({event.event_type}): {error}. "
            f"Retry {retry_count + 1}/{max_retries}",
            exc_info=True
        )

        # Send to DLQ if we've exceeded max retries
        if retry_count >= max_retries:
            logger.warning(
                f"Event {event_id} exceeded max retries ({max_retries}). "
                f"Sending to DLQ."
            )

            await producer.send_to_dlq(
                original_event=event,
                original_topic=original_topic,
                error=error,
                retry_count=retry_count
            )

            # Clear retry count for this event
            retry_counts.pop(event_id, None)
        else:
            # Could implement retry logic here if needed
            # For now, the event will be retried when Kafka redelivers it
            pass

    return handle_error_with_dlq


def create_immediate_dlq_handler(
        producer: UnifiedProducer,
        original_topic: str
) -> Callable[[Exception, BaseEvent], Awaitable[None]]:
    """
    Create an error handler that immediately sends failed events to DLQ.
    
    This is useful for critical errors where retry won't help.
    
    Args:
        producer: The Kafka producer to use for sending to DLQ
        original_topic: The topic where the event originally failed
        
    Returns:
        An async error handler function suitable for UnifiedConsumer.register_error_callback
    """

    async def handle_error_immediate_dlq(error: Exception, event: BaseEvent) -> None:
        """
        Handle processing errors by immediately sending to DLQ.
        
        Args:
            error: The exception that occurred
            event: The event that failed processing
        """
        event_id = event.event_id or "unknown"

        logger.error(
            f"Critical error processing event {event_id} ({event.event_type}): {error}. "
            f"Sending immediately to DLQ.",
            exc_info=True
        )

        await producer.send_to_dlq(
            original_event=event,
            original_topic=original_topic,
            error=error,
            retry_count=0
        )

    return handle_error_immediate_dlq
