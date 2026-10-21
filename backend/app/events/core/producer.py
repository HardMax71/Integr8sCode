import structlog
from aiokafka.errors import KafkaError
from faststream.exceptions import IncorrectState
from opentelemetry import trace
from pymongo.errors import PyMongoError

from app.db import EventRepository
from app.domain.events import DomainEvent
from app.events.core.transport import KafkaEventTransport

_PUBLISH_ERRORS: tuple[type[Exception], ...] = (KafkaError, IncorrectState)
PRODUCE_ERRORS: tuple[type[Exception], ...] = (PyMongoError, *_PUBLISH_ERRORS)


class UnifiedProducer:
    """Stores each event in MongoDB, then publishes it to Kafka."""

    def __init__(
        self,
        event_repository: EventRepository,
        transport: KafkaEventTransport,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
    ):
        self._event_repository = event_repository
        self._transport = transport
        self.logger = logger
        self._tracer = tracer

    async def produce(self, event_to_produce: DomainEvent, key: str) -> None:
        """Store the event, then publish it; a MongoDB or Kafka error goes to the caller."""
        event_type = event_to_produce.event_type
        with self._tracer.start_as_current_span("publish_event") as span:
            span.set_attribute("event.type", event_type)
            if event_to_produce.aggregate_id:
                span.set_attribute("aggregate.id", event_to_produce.aggregate_id)
            await self._event_repository.store_event(event_to_produce)
            await self._transport.publish(event_to_produce, event_type, key)

    async def produce_or_log(self, event_to_produce: DomainEvent, key: str) -> None:
        """Store the event, then publish it, logging a Kafka error instead of raising it.

        For events sent after their work is done, so a Kafka outage doesn't fail the request or job
        that sent them. A MongoDB error still raises, since the stored event is the record.
        """
        try:
            await self.produce(event_to_produce, key)
        except _PUBLISH_ERRORS:
            self.logger.error(
                "Event stored but not published",
                event_id=event_to_produce.event_id,
                event_type=event_to_produce.event_type,
                exc_info=True,
            )
