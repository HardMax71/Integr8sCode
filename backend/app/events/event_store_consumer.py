import logging

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from opentelemetry.trace import SpanKind

from app.core.metrics import EventMetrics
from app.core.tracing.utils import trace_span
from app.domain.enums.kafka import GroupId
from app.domain.events.typed import DomainEvent
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager


class EventStoreConsumer:
    """Consumes events from Kafka and stores them in MongoDB.

    Pure logic class - lifecycle managed by DI provider.
    Uses Kafka's native batching via getmany().
    """

    def __init__(
        self,
        event_store: EventStore,
        consumer: AIOKafkaConsumer,
        schema_registry_manager: SchemaRegistryManager,
        logger: logging.Logger,
        event_metrics: EventMetrics,
        group_id: GroupId = GroupId.EVENT_STORE_CONSUMER,
        batch_size: int = 100,
        batch_timeout_ms: int = 5000,
    ):
        self.event_store = event_store
        self.consumer = consumer
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.logger = logger
        self.event_metrics = event_metrics
        self.schema_registry_manager = schema_registry_manager

    async def process_batch(self) -> None:
        """Process a single batch of messages from Kafka.

        Called repeatedly by DI provider's background task.
        """
        batch_data: dict[TopicPartition, list[ConsumerRecord[bytes, bytes]]] = await self.consumer.getmany(
            timeout_ms=self.batch_timeout_ms,
            max_records=self.batch_size,
        )

        if not batch_data:
            return

        events: list[DomainEvent] = []
        for tp, messages in batch_data.items():
            for msg in messages:
                try:
                    event = await self.schema_registry_manager.deserialize_event(msg.value, msg.topic)
                    events.append(event)
                    self.event_metrics.record_kafka_message_consumed(
                        topic=msg.topic,
                        consumer_group=str(self.group_id),
                    )
                except Exception as e:
                    self.logger.error(f"Failed to deserialize message from {tp}: {e}", exc_info=True)

        if events:
            await self._store_batch(events)
            await self.consumer.commit()

    async def _store_batch(self, events: list[DomainEvent]) -> None:
        """Store a batch of events."""
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
