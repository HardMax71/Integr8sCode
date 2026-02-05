import asyncio
import logging
import socket
from datetime import datetime, timezone

from faststream.kafka import KafkaBroker

from app.core.metrics import EventMetrics
from app.core.tracing.utils import inject_trace_context
from app.db.repositories.event_repository import EventRepository
from app.dlq.models import DLQMessageStatus
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent
from app.infrastructure.kafka.mappings import EVENT_TYPE_TO_TOPIC
from app.settings import Settings


class UnifiedProducer:
    """Kafka producer backed by FastStream KafkaBroker.

    FastStream handles Pydantic JSON serialization natively.
    The broker's lifecycle is managed externally (FastStream app or FastAPI lifespan).
    """

    def __init__(
        self,
        broker: KafkaBroker,
        event_repository: EventRepository,
        logger: logging.Logger,
        settings: Settings,
        event_metrics: EventMetrics,
    ):
        self._broker = broker
        self._event_repository = event_repository
        self.logger = logger
        self._event_metrics = event_metrics
        self._topic_prefix = settings.KAFKA_TOPIC_PREFIX

    async def produce(self, event_to_produce: DomainEvent, key: str) -> None:
        """Persist event to MongoDB, then publish to Kafka."""
        await self._event_repository.store_event(event_to_produce)
        topic = f"{self._topic_prefix}{EVENT_TYPE_TO_TOPIC[event_to_produce.event_type]}"
        try:
            headers = inject_trace_context({
                "event_type": event_to_produce.event_type,
                "correlation_id": event_to_produce.metadata.correlation_id or "",
                "service": event_to_produce.metadata.service_name,
            })

            await self._broker.publish(
                message=event_to_produce,
                topic=topic,
                key=key.encode(),
                headers=headers,
            )

            self._event_metrics.record_kafka_message_produced(topic)
            self.logger.debug(f"Event {event_to_produce.event_type} sent to topic: {topic}")

        except Exception as e:
            self._event_metrics.record_kafka_production_error(topic=topic, error_type=type(e).__name__)
            self.logger.error(f"Failed to produce message: {e}")
            raise

    async def send_to_dlq(
        self, original_event: DomainEvent, original_topic: str, error: Exception, retry_count: int = 0
    ) -> None:
        """Send a failed event to the Dead Letter Queue."""
        try:
            current_task = asyncio.current_task()
            task_name = current_task.get_name() if current_task else "main"
            producer_id = f"{socket.gethostname()}-{task_name}"

            dlq_topic = f"{self._topic_prefix}{KafkaTopic.DEAD_LETTER_QUEUE}"

            headers = inject_trace_context({
                "event_type": original_event.event_type,
                "original_topic": original_topic,
                "error_type": type(error).__name__,
                "error": str(error),
                "retry_count": str(retry_count),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "status": DLQMessageStatus.PENDING,
                "producer_id": producer_id,
            })

            await self._broker.publish(
                message=original_event,
                topic=dlq_topic,
                key=original_event.event_id.encode() if original_event.event_id else None,
                headers=headers,
            )

            self._event_metrics.record_kafka_message_produced(dlq_topic)
            self.logger.warning(
                f"Event {original_event.event_id} sent to DLQ. "
                f"Original topic: {original_topic}, Error: {error}, "
                f"Retry count: {retry_count}"
            )

        except Exception as e:
            self.logger.critical(
                f"Failed to send event {original_event.event_id} to DLQ: {e}. Original error: {error}", exc_info=True
            )
