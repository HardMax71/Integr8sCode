import logging

from opentelemetry.trace import SpanKind

from app.core.metrics import EventMetrics
from app.core.tracing.utils import trace_span
from app.domain.events.typed import DomainEvent
from app.events.event_store import EventStore


class EventStoreService:
    """Stores domain events to MongoDB for audit/replay.

    Pure storage service - no consumer, no loops.
    Called by FastStream subscribers to archive events.
    """

    def __init__(
        self,
        event_store: EventStore,
        logger: logging.Logger,
        event_metrics: EventMetrics,
    ):
        self.event_store = event_store
        self.logger = logger
        self.event_metrics = event_metrics

    async def store_event(self, event: DomainEvent, topic: str, consumer_group: str) -> bool:
        """Store a single event. Called by FastStream handler.

        Returns True if stored, False if duplicate/failed.
        """
        with trace_span(
            name="event_store_service.store_event",
            kind=SpanKind.CONSUMER,
            attributes={"event.type": event.event_type, "event.id": event.event_id},
        ):
            stored = await self.event_store.store_event(event)

        if stored:
            self.event_metrics.record_kafka_message_consumed(topic=topic, consumer_group=consumer_group)
            self.logger.debug(f"Stored event {event.event_id}")
        else:
            self.logger.debug(f"Duplicate event {event.event_id}, skipped")

        return stored

    async def store_batch(self, events: list[DomainEvent]) -> dict[str, int]:
        """Store a batch of events. For bulk operations."""
        self.logger.info(f"Storing batch of {len(events)} events")

        with trace_span(
            name="event_store.store_batch",
            kind=SpanKind.CONSUMER,
            attributes={"events.batch.count": len(events)},
        ):
            results = await self.event_store.store_batch(events)

        self.logger.info(
            f"Stored event batch: total={results['total']}, "
            f"stored={results['stored']}, duplicates={results['duplicates']}, "
            f"failed={results['failed']}"
        )
        return results
