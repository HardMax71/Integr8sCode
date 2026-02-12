import logging

from faststream.kafka import KafkaBroker

from app.core.metrics import EventMetrics
from app.db.repositories import EventRepository
from app.domain.events import DomainEvent
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
        topic = f"{self._topic_prefix}{event_to_produce.event_type}"
        try:
            await self._broker.publish(
                message=event_to_produce,
                topic=topic,
                key=key.encode(),
            )

            self._event_metrics.record_kafka_message_produced(topic)
            self.logger.debug(f"Event {event_to_produce.event_type} sent to topic: {topic}")

        except Exception as e:
            self._event_metrics.record_kafka_production_error(topic=topic, error_type=type(e).__name__)
            self.logger.error(f"Failed to produce message: {e}")
            raise
