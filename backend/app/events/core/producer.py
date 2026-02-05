import asyncio
import logging
import socket
from datetime import datetime, timezone

from faststream.kafka import KafkaBroker

from app.db.repositories.event_repository import EventRepository
from app.dlq.models import DLQMessageStatus
from app.domain.events.typed import BaseEvent
from app.settings import Settings


class EventPublisher:
    """Minimal event publisher: persist to MongoDB, then publish to Kafka.

    Metrics and tracing are handled by FastStream middleware (KafkaPrometheusMiddleware,
    KafkaTelemetryMiddleware) - no manual instrumentation needed here.

    Topic routing: 1 event type = 1 topic.
    Topic name derived from class: ExecutionRequestedEvent -> execution_requested
    """

    def __init__(
        self,
        broker: KafkaBroker,
        event_repository: EventRepository,
        logger: logging.Logger,
        settings: Settings,
    ):
        self._broker = broker
        self._repo = event_repository
        self._logger = logger
        self._prefix = settings.KAFKA_TOPIC_PREFIX

    async def publish(self, event: BaseEvent, key: str | None = None) -> str:
        """Persist event to MongoDB, then publish to Kafka.

        Args:
            event: The domain event to publish
            key: Optional Kafka partition key (defaults to aggregate_id or event_id)

        Returns:
            The event_id of the published event
        """
        await self._repo.store_event(event)

        topic = type(event).topic(self._prefix)
        effective_key = key or event.aggregate_id or event.event_id

        await self._broker.publish(
            message=event,
            topic=topic,
            key=effective_key.encode() if effective_key else None,
        )

        return event.event_id

    async def send_to_dlq(
        self,
        event: BaseEvent,
        original_topic: str,
        error: Exception,
        retry_count: int = 0,
    ) -> None:
        """Send a failed event to the Dead Letter Queue."""
        current_task = asyncio.current_task()
        task_name = current_task.get_name() if current_task else "main"
        producer_id = f"{socket.gethostname()}-{task_name}"

        await self._broker.publish(
            message=event,
            topic=f"{self._prefix}dead_letter_queue",
            key=event.event_id.encode() if event.event_id else None,
            headers={
                "original_topic": original_topic,
                "error_type": type(error).__name__,
                "error": str(error),
                "retry_count": str(retry_count),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "status": DLQMessageStatus.PENDING,
                "producer_id": producer_id,
            },
        )

        self._logger.warning(
            f"Event {event.event_id} sent to DLQ. "
            f"Original topic: {original_topic}, Error: {error}"
        )
