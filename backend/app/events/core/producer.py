import structlog
from faststream.kafka import KafkaBroker

from app.core.metrics import EventMetrics
from app.db.repositories import EventRepository
from app.domain.events import DomainEvent


class UnifiedProducer:
    """Kafka producer backed by FastStream KafkaBroker.

    FastStream handles Pydantic JSON serialization natively.
    The broker's lifecycle is managed externally (FastStream app or FastAPI lifespan).
    """

    def __init__(
        self,
        broker: KafkaBroker,
        event_repository: EventRepository,
        logger: structlog.stdlib.BoundLogger,
        event_metrics: EventMetrics,
    ):
        self._broker = broker
        self._event_repository = event_repository
        self.logger = logger
        self._event_metrics = event_metrics

    async def produce(self, event_to_produce: DomainEvent, key: str) -> None:
        """Persist event to MongoDB, then publish to Kafka.

        On Kafka publish failure, the event is marked as failed-to-publish
        in MongoDB before the exception propagates.
        """
        await self._event_repository.store_event(event_to_produce)
        topic = event_to_produce.event_type
        try:
            await self._broker.publish(
                message=event_to_produce,
                topic=topic,
                key=key.encode(),
            )

            self._event_metrics.record_kafka_message_produced(topic)
            self.logger.debug("Event sent to topic", event_type=event_to_produce.event_type, topic=topic)

        except Exception as e:
            self._event_metrics.record_kafka_production_error(topic=topic, error_type=type(e).__name__)
            self.logger.error("Failed to produce message", topic=topic, error=str(e))
            await self._event_repository.mark_publish_failed(event_to_produce.event_id)
            raise
