import asyncio

from app.core.logging import logger
from app.db.schema.schema_manager import SchemaManager
from app.domain.enums.events import EventType
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.dlq_handler import create_dlq_error_handler
from app.events.core.producer import UnifiedProducer
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.settings import get_settings


class EventStoreConsumer:
    """Consumes events from Kafka and stores them in MongoDB."""

    def __init__(
            self,
            event_store: EventStore,
            topics: list[KafkaTopic],
            schema_registry_manager: SchemaRegistryManager,
            producer: UnifiedProducer | None = None,
            group_id: GroupId = GroupId.EVENT_STORE_CONSUMER,
            batch_size: int = 100,
            batch_timeout_seconds: float = 5.0,
    ):
        self.event_store = event_store
        self.topics = topics
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout_seconds
        self.consumer: UnifiedConsumer | None = None
        self.schema_registry_manager = schema_registry_manager
        self.dispatcher = EventDispatcher()
        self.producer = producer  # For DLQ handling
        self._batch_buffer: list[BaseEvent] = []
        self._batch_lock = asyncio.Lock()
        self._last_batch_time = asyncio.get_event_loop().time()
        self._batch_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start consuming and storing events."""
        if self._running:
            return

        await SchemaManager(self.event_store.db).apply_all()

        settings = get_settings()
        config = ConsumerConfig(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=self.group_id,
            enable_auto_commit=False,
            max_poll_records=self.batch_size
        )

        self.consumer = UnifiedConsumer(
            config,
            event_dispatcher=self.dispatcher
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
                max_retries=3
            )
            self.consumer.register_error_callback(dlq_handler)
        else:
            # Fallback to simple logging
            self.consumer.register_error_callback(self._handle_error_with_event)

        await self.consumer.start(self.topics)
        self._running = True

        self._batch_task = asyncio.create_task(self._batch_processor())

        logger.info(f"Event store consumer started for topics: {self.topics}")

    async def stop(self) -> None:
        """Stop consumer."""
        if not self._running:
            return

        self._running = False

        await self._flush_batch()

        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        if self.consumer:
            await self.consumer.stop()

        logger.info("Event store consumer stopped")

    async def _handle_event(self, event: BaseEvent) -> None:
        """Handle incoming event from dispatcher."""
        logger.info(f"Event store received event: {event.event_type} - {event.event_id}")

        async with self._batch_lock:
            self._batch_buffer.append(event)

            if len(self._batch_buffer) >= self.batch_size:
                await self._flush_batch()

    async def _handle_error_with_event(self, error: Exception, event: BaseEvent) -> None:
        """Handle processing errors with event context."""
        logger.error(
            f"Error processing event {event.event_id} ({event.event_type}): {error}",
            exc_info=True
        )

    async def _batch_processor(self) -> None:
        """Periodically flush batches based on timeout."""
        while self._running:
            try:
                await asyncio.sleep(1)

                async with self._batch_lock:
                    time_since_last_batch = asyncio.get_event_loop().time() - self._last_batch_time

                    if (self._batch_buffer and
                            time_since_last_batch >= self.batch_timeout):
                        await self._flush_batch()

            except Exception as e:
                logger.error(f"Error in batch processor: {e}")

    async def _flush_batch(self) -> None:
        if not self._batch_buffer:
            return

        batch = self._batch_buffer.copy()
        self._batch_buffer.clear()
        self._last_batch_time = asyncio.get_event_loop().time()

        logger.info(f"Event store flushing batch of {len(batch)} events")

        results = await self.event_store.store_batch(batch)

        logger.info(
            f"Stored event batch: total={results['total']}, "
            f"stored={results['stored']}, duplicates={results['duplicates']}, "
            f"failed={results['failed']}"
        )


def create_event_store_consumer(
        event_store: EventStore,
        topics: list[KafkaTopic],
        schema_registry_manager: SchemaRegistryManager,
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
        producer=producer
    )
