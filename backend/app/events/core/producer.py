import time

from aiokafka.errors import KafkaError
from faststream.exceptions import IncorrectState
from opentelemetry import trace
from pymongo.errors import PyMongoError

from app.core.metrics import EventMetrics
from app.db import EventRepository
from app.domain.events import DomainEvent
from app.events.core.transport import KafkaEventTransport

tracer = trace.get_tracer(__name__)

PRODUCE_ERRORS: tuple[type[Exception], ...] = (PyMongoError, KafkaError, IncorrectState)


class UnifiedProducer:
    """Orchestrates the store-then-publish outbox pattern.

    Persists the event to MongoDB, then delegates to KafkaEventTransport
    for Kafka delivery. On transport failure the event is marked as
    failed-to-publish before the exception propagates.
    """

    def __init__(
        self,
        event_repository: EventRepository,
        transport: KafkaEventTransport,
        event_metrics: EventMetrics,
    ):
        self._event_repository = event_repository
        self._transport = transport
        self._metrics = event_metrics

    async def produce(self, event_to_produce: DomainEvent, key: str) -> None:
        """Persist event to MongoDB, then publish to Kafka.

        On Kafka publish failure, the event is marked as failed-to-publish
        in MongoDB before the exception propagates.
        """
        event_type = event_to_produce.event_type
        with tracer.start_as_current_span("publish_event") as span:
            span.set_attribute("event.type", event_type)
            if event_to_produce.aggregate_id:
                span.set_attribute("aggregate.id", event_to_produce.aggregate_id)
            start = time.monotonic()
            await self._event_repository.store_event(event_to_produce)
            try:
                await self._transport.publish(event_to_produce, event_type, key)
            except Exception:
                await self._event_repository.mark_publish_failed(event_to_produce.event_id)
                raise
            self._metrics.record_event_published(event_type)
            self._metrics.record_event_processing_duration(time.monotonic() - start, event_type)
