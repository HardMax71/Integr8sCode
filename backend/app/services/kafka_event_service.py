import logging
import time

from opentelemetry import trace

from app.core.metrics import EventMetrics
from app.domain.events import DomainEvent
from app.events.core import UnifiedProducer
from app.settings import Settings

tracer = trace.get_tracer(__name__)


class KafkaEventService:
    def __init__(
        self,
        kafka_producer: UnifiedProducer,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
    ):
        self.kafka_producer = kafka_producer
        self.logger = logger
        self.metrics = event_metrics
        self.settings = settings

    async def publish_event(self, event: DomainEvent, key: str) -> str:
        """Publish a typed DomainEvent to Kafka.

        The producer persists the event to MongoDB before publishing.
        """
        with tracer.start_as_current_span("publish_event") as span:
            span.set_attribute("event.type", event.event_type)
            if event.aggregate_id:
                span.set_attribute("aggregate.id", event.aggregate_id)

            start_time = time.time()

            await self.kafka_producer.produce(event_to_produce=event, key=key)
            self.metrics.record_event_published(event.event_type)
            self.metrics.record_event_processing_duration(time.time() - start_time, event.event_type)
            self.logger.info("Event published", extra={"event_type": event.event_type, "event_id": event.event_id})
            return event.event_id
