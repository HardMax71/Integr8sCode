from app.db import EventRepository
from app.domain.events import DomainEvent
from app.events.core.transport import KafkaEventTransport


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
    ):
        self._event_repository = event_repository
        self._transport = transport

    async def produce(self, event_to_produce: DomainEvent, key: str) -> None:
        """Persist event to MongoDB, then publish to Kafka.

        On Kafka publish failure, the event is marked as failed-to-publish
        in MongoDB before the exception propagates.
        """
        await self._event_repository.store_event(event_to_produce)
        try:
            await self._transport.publish(event_to_produce, event_to_produce.event_type, key)
        except Exception:
            await self._event_repository.mark_publish_failed(event_to_produce.event_id)
            raise
