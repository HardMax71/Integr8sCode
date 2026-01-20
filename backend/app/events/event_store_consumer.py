import asyncio
import logging

from aiokafka import AIOKafkaConsumer
from opentelemetry.trace import SpanKind

from app.core.metrics import EventMetrics
from app.core.tracing.utils import trace_span
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings


class EventStoreConsumer:
    """Consumes events from Kafka and stores them in MongoDB.

    Uses Kafka's native batching via getmany() - no application-level buffering.
    Kafka's fetch_max_wait_ms controls batch timing at the protocol level.

    Usage:
        consumer = EventStoreConsumer(...)
        await consumer.run()  # Blocks until cancelled
    """

    def __init__(
        self,
        event_store: EventStore,
        topics: list[KafkaTopic],
        schema_registry_manager: SchemaRegistryManager,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
        group_id: GroupId = GroupId.EVENT_STORE_CONSUMER,
        batch_size: int = 100,
        batch_timeout_ms: int = 5000,
    ):
        """Store dependencies. All work happens in run()."""
        self.event_store = event_store
        self.topics = topics
        self.settings = settings
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.logger = logger
        self.event_metrics = event_metrics
        self.schema_registry_manager = schema_registry_manager

    async def run(self) -> None:
        """Run the consumer. Blocks until cancelled.

        Creates consumer, starts it, runs batch loop, stops on cancellation.
        Uses getmany() which blocks on Kafka's fetch - no polling, no timers.
        """
        self.logger.info("Event store consumer starting...")

        topic_strings = [f"{self.settings.KAFKA_TOPIC_PREFIX}{topic}" for topic in self.topics]

        consumer = AIOKafkaConsumer(
            *topic_strings,
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"{self.group_id}.{self.settings.KAFKA_GROUP_SUFFIX}",
            enable_auto_commit=False,
            max_poll_records=self.batch_size,
            session_timeout_ms=self.settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self.settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            max_poll_interval_ms=self.settings.KAFKA_MAX_POLL_INTERVAL_MS,
            request_timeout_ms=self.settings.KAFKA_REQUEST_TIMEOUT_MS,
            fetch_max_wait_ms=self.batch_timeout_ms,
        )

        await consumer.start()
        self.logger.info(f"Event store consumer initialized for topics: {topic_strings}")

        try:
            while True:
                # getmany() blocks until Kafka has data OR fetch_max_wait_ms expires
                # This is NOT polling - it's async waiting on the network socket
                batch_data = await consumer.getmany(
                    timeout_ms=self.batch_timeout_ms,
                    max_records=self.batch_size,
                )

                if not batch_data:
                    continue

                # Deserialize all messages in the batch
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
                    await consumer.commit()

        except asyncio.CancelledError:
            self.logger.info("Event store consumer cancelled")
        finally:
            await consumer.stop()
            self.logger.info("Event store consumer stopped")

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
