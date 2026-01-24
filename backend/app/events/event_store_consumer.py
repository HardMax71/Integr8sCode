import asyncio
import logging

from opentelemetry.trace import SpanKind

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics import EventMetrics
from app.core.tracing.utils import trace_span
from app.domain.enums.events import EventType
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer, create_dlq_error_handler
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings


class EventStoreConsumer(LifecycleEnabled):
    """Consumes events from Kafka and stores them in MongoDB."""

    def __init__(
        self,
        event_store: EventStore,
        topics: list[KafkaTopic],
        schema_registry_manager: SchemaRegistryManager,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
        producer: UnifiedProducer | None = None,
        group_id: GroupId = GroupId.EVENT_STORE_CONSUMER,
        batch_size: int = 100,
        batch_timeout_seconds: float = 5.0,
    ):
        super().__init__()
        self.event_store = event_store
        self.topics = topics
        self.settings = settings
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout_seconds
        self.logger = logger
        self.event_metrics = event_metrics
        self.consumer: UnifiedConsumer | None = None
        self.schema_registry_manager = schema_registry_manager
        self.dispatcher = EventDispatcher(logger)
        self.producer = producer  # For DLQ handling
        self._batch_buffer: list[DomainEvent] = []
        self._batch_lock = asyncio.Lock()
        self._last_batch_time: float = 0.0
        self._batch_task: asyncio.Task[None] | None = None

    async def _on_start(self) -> None:
        """Start consuming and storing events."""
        self._last_batch_time = asyncio.get_running_loop().time()
        config = ConsumerConfig(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=self.group_id,
            enable_auto_commit=False,
            max_poll_records=self.batch_size,
            session_timeout_ms=self.settings.KAFKA_SESSION_TIMEOUT_MS,
            heartbeat_interval_ms=self.settings.KAFKA_HEARTBEAT_INTERVAL_MS,
            max_poll_interval_ms=self.settings.KAFKA_MAX_POLL_INTERVAL_MS,
            request_timeout_ms=self.settings.KAFKA_REQUEST_TIMEOUT_MS,
        )

        self.consumer = UnifiedConsumer(
            config,
            event_dispatcher=self.dispatcher,
            schema_registry=self.schema_registry_manager,
            settings=self.settings,
            logger=self.logger,
            event_metrics=self.event_metrics,
        )

        # Register handler for all event types - store everything
        for event_type in EventType:
            self.dispatcher.register(event_type)(self._handle_event)

        # Register error callback - use DLQ if producer is available
        if self.producer:
            # Use DLQ handler with retry logic
            dlq_handler = create_dlq_error_handler(
                producer=self.producer,
                original_topic="event-store",  # Generic topic name for event store
                logger=self.logger,
                max_retries=3,
            )
            self.consumer.register_error_callback(dlq_handler)
        else:
            # Fallback to simple logging
            self.consumer.register_error_callback(self._handle_error_with_event)

        await self.consumer.start(self.topics)

        self._batch_task = asyncio.create_task(self._batch_processor())

        self.logger.info(f"Event store consumer started for topics: {self.topics}")

    async def _on_stop(self) -> None:
        """Stop consumer."""
        await self._flush_batch()

        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        if self.consumer:
            await self.consumer.stop()

        self.logger.info("Event store consumer stopped")

    async def _handle_event(self, event: DomainEvent) -> None:
        """Handle incoming event from dispatcher."""
        self.logger.info(f"Event store received event: {event.event_type} - {event.event_id}")

        async with self._batch_lock:
            self._batch_buffer.append(event)

            if len(self._batch_buffer) >= self.batch_size:
                await self._flush_batch()

    async def _handle_error_with_event(self, error: Exception, event: DomainEvent) -> None:
        """Handle processing errors with event context."""
        self.logger.error(f"Error processing event {event.event_id} ({event.event_type}): {error}", exc_info=True)

    async def _batch_processor(self) -> None:
        """Periodically flush batches based on timeout."""
        while self.is_running:
            try:
                await asyncio.sleep(1)

                async with self._batch_lock:
                    time_since_last_batch = asyncio.get_running_loop().time() - self._last_batch_time

                    if self._batch_buffer and time_since_last_batch >= self.batch_timeout:
                        await self._flush_batch()

            except Exception as e:
                self.logger.error(f"Error in batch processor: {e}")

    async def _flush_batch(self) -> None:
        if not self._batch_buffer:
            return

        batch = self._batch_buffer.copy()
        self._batch_buffer.clear()
        self._last_batch_time = asyncio.get_running_loop().time()

        self.logger.info(f"Event store flushing batch of {len(batch)} events")
        with trace_span(
            name="event_store.flush_batch",
            kind=SpanKind.CONSUMER,
            attributes={"events.batch.count": len(batch)},
        ):
            results = await self.event_store.store_batch(batch)

        self.logger.info(
            f"Stored event batch: total={results['total']}, "
            f"stored={results['stored']}, duplicates={results['duplicates']}, "
            f"failed={results['failed']}"
        )


def create_event_store_consumer(
    event_store: EventStore,
    topics: list[KafkaTopic],
    schema_registry_manager: SchemaRegistryManager,
    settings: Settings,
    logger: logging.Logger,
    event_metrics: EventMetrics,
    producer: UnifiedProducer | None = None,
    group_id: GroupId = GroupId.EVENT_STORE_CONSUMER,
    batch_size: int = 100,
    batch_timeout_seconds: float = 5.0,
) -> EventStoreConsumer:
    return EventStoreConsumer(
        event_store=event_store,
        topics=topics,
        group_id=group_id,
        batch_size=batch_size,
        batch_timeout_seconds=batch_timeout_seconds,
        schema_registry_manager=schema_registry_manager,
        settings=settings,
        logger=logger,
        event_metrics=event_metrics,
        producer=producer,
    )
