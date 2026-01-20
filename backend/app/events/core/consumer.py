import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, TopicPartition
from opentelemetry.trace import SpanKind

from app.core.metrics import EventMetrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings

from .dispatcher import EventDispatcher
from .types import ConsumerConfig


class UnifiedConsumer:
    """Kafka consumer with framework-style run().

    No loops in user code. Register handlers, call run(), handlers get called.

    Usage:
        dispatcher = EventDispatcher()
        dispatcher.register(EventType.FOO, handle_foo)

        consumer = UnifiedConsumer(..., dispatcher=dispatcher)
        await consumer.run()  # Blocks, calls handlers when events arrive
    """

    def __init__(
        self,
        config: ConsumerConfig,
        dispatcher: EventDispatcher,
        schema_registry: SchemaRegistryManager,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
        topics: list[KafkaTopic],
        error_callback: Callable[[Exception, DomainEvent], Awaitable[None]] | None = None,
    ):
        self._config = config
        self._dispatcher = dispatcher
        self._schema_registry = schema_registry
        self._event_metrics = event_metrics
        self._topics = [f"{settings.KAFKA_TOPIC_PREFIX}{t}" for t in topics]
        self._error_callback = error_callback
        self.logger = logger
        self._consumer: AIOKafkaConsumer | None = None

    async def run(self) -> None:
        """Run the consumer. Blocks until stopped. Calls registered handlers."""
        tracer = get_tracer()

        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._config.bootstrap_servers,
            group_id=self._config.group_id,
            client_id=self._config.client_id,
            auto_offset_reset=self._config.auto_offset_reset,
            enable_auto_commit=self._config.enable_auto_commit,
            session_timeout_ms=self._config.session_timeout_ms,
            heartbeat_interval_ms=self._config.heartbeat_interval_ms,
            max_poll_interval_ms=self._config.max_poll_interval_ms,
            request_timeout_ms=self._config.request_timeout_ms,
            fetch_min_bytes=self._config.fetch_min_bytes,
            fetch_max_wait_ms=self._config.fetch_max_wait_ms,
        )

        await self._consumer.start()
        self.logger.info(f"Consumer running for topics: {self._topics}")

        try:
            async for msg in self._consumer:
                if not msg.value:
                    continue

                try:
                    event = await self._schema_registry.deserialize_event(msg.value, msg.topic)

                    headers = {k: v.decode() if isinstance(v, bytes) else v for k, v in (msg.headers or [])}
                    ctx = extract_trace_context(headers)

                    with tracer.start_as_current_span(
                        "kafka.consume",
                        context=ctx,
                        kind=SpanKind.CONSUMER,
                        attributes={
                            EventAttributes.KAFKA_TOPIC: msg.topic,
                            EventAttributes.KAFKA_PARTITION: msg.partition,
                            EventAttributes.KAFKA_OFFSET: msg.offset,
                            EventAttributes.EVENT_TYPE: event.event_type,
                            EventAttributes.EVENT_ID: event.event_id,
                        },
                    ):
                        await self._dispatcher.dispatch(event)

                    if not self._config.enable_auto_commit:
                        await self._consumer.commit()

                    self._event_metrics.record_kafka_message_consumed(msg.topic, self._config.group_id)

                except Exception as e:
                    self.logger.error(f"Error processing message: {e}", exc_info=True)
                    self._event_metrics.record_kafka_consumption_error(
                        msg.topic, self._config.group_id, type(e).__name__
                    )
                    if self._error_callback:
                        await self._error_callback(e, event)

        finally:
            await self._consumer.stop()
            self.logger.info("Consumer stopped")

    async def seek_to_beginning(self) -> None:
        if self._consumer and (assignment := self._consumer.assignment()):
            await self._consumer.seek_to_beginning(*assignment)

    async def seek_to_end(self) -> None:
        if self._consumer and (assignment := self._consumer.assignment()):
            await self._consumer.seek_to_end(*assignment)

    async def seek_to_offset(self, topic: str, partition: int, offset: int) -> None:
        if self._consumer:
            self._consumer.seek(TopicPartition(topic, partition), offset)
