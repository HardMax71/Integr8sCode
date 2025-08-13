"""
Unified Kafka consumer with comprehensive feature set.

This module provides a high-performance, async Kafka consumer that combines
the best features from multiple implementations into a single, cohesive API.

Features:
- Native async support with aiokafka
- Event handler registration pattern
- Schema registry integration for Avro
- Dead Letter Queue (DLQ) support
- Distributed tracing with OpenTelemetry
- Circuit breaker pattern
- Flexible offset management strategies
- Consumer group coordination
- Type-safe with Python 3.12+ features

Note: No globals, no magic methods, no excessive branching.
"""

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from itertools import chain
from typing import Any, TypeAlias, TypeVar

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.errors import CommitFailedError
from aiokafka.structs import ConsumerRecord
from opentelemetry.trace import SpanKind, Status, StatusCode

from app.config import get_settings
from app.core.logging import logger
from app.core.tracing import (
    EventAttributes,
    add_span_attributes,
    add_span_event,
    context,
    extract_trace_context,
    trace_span,
)
from app.events.core.errors import DeserializationError
from app.events.core.mapping import get_default_schema_mapping
from app.events.core.metrics import (
    BATCH_SIZE_PROCESSED,
    EVENTS_CONSUMED,
    EVENTS_PROCESSING_FAILED,
    PROCESSING_DURATION,
)
from app.events.kafka.cb import (
    CircuitBreakerType,
    KafkaCircuitBreaker,
    KafkaCircuitBreakerManager,
)
from app.events.kafka.metrics.metrics import (
    KAFKA_CONSUMER_BYTES_CONSUMED,
    KAFKA_CONSUMER_COMMITTED_OFFSET,
    KAFKA_CONSUMER_LAG,
    KAFKA_CONSUMER_OFFSET,
)
from app.events.schema.schema_registry import get_schema_registry
from app.events.schema.serialization import EventSerializer
from app.schemas_avro.event_schemas import BaseEvent

# Type aliases
EventHandler: TypeAlias = Callable[[BaseEvent, ConsumerRecord], Any]
ErrorHandler: TypeAlias = Callable[[Exception, ConsumerRecord, BaseEvent | None], Any]
PartitionOffsets: TypeAlias = dict[TopicPartition, int]
SchemaMapping: TypeAlias = dict[str, str]

# Event type for handlers
EventType = TypeVar("EventType", BaseEvent, dict[str, Any])


class OffsetStrategy(StrEnum):
    """Consumer offset management strategies."""
    MANUAL = "manual"
    AUTO_COMMIT = "auto_commit"
    BATCH_COMMIT = "batch_commit"


class ProcessingMode(StrEnum):
    """Message processing modes."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    BATCH = "batch"


@dataclass(frozen=True, slots=True)
class ConsumerConfig:
    """Configuration for unified Kafka consumer."""
    bootstrap_servers: str | None = None
    group_id: str | None = None
    topics: list[str] = field(default_factory=list)
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    auto_commit_interval_ms: int = 5000
    session_timeout_ms: int = 30000
    heartbeat_interval_ms: int = 3000
    max_poll_records: int = 500
    max_poll_interval_ms: int = 300000
    offset_strategy: OffsetStrategy = OffsetStrategy.BATCH_COMMIT
    processing_mode: ProcessingMode = ProcessingMode.SEQUENTIAL
    retry_failed_events: bool = True
    max_retries: int = 3
    retry_delay_ms: int = 1000
    commit_interval_messages: int = 100
    commit_interval_seconds: float = 10.0
    enable_dlq: bool = True
    dlq_topic: str | None = None
    schema_registry_url: str | None = None
    enable_schema_registry: bool = True
    schema_mapping: SchemaMapping = field(default_factory=dict)
    metrics_update_interval: float = 30.0

    def __post_init__(self) -> None:
        settings = get_settings()
        # Use object.__setattr__ to modify frozen dataclass
        if not self.bootstrap_servers:
            object.__setattr__(self, "bootstrap_servers", settings.KAFKA_BOOTSTRAP_SERVERS)
        if not self.group_id:
            object.__setattr__(self, "group_id", settings.KAFKA_CONSUMER_GROUP_ID)
        if not self.dlq_topic:
            object.__setattr__(self, "dlq_topic", settings.KAFKA_DLQ_TOPIC)
        if not self.schema_registry_url:
            object.__setattr__(self, "schema_registry_url", settings.SCHEMA_REGISTRY_URL)

        # Use default schema mappings from centralized mapping
        if not self.schema_mapping:
            object.__setattr__(self, "schema_mapping", get_default_schema_mapping())


@dataclass
class ConsumerMetrics:
    """Runtime metrics for consumer."""
    messages_processed: int = 0
    messages_failed: int = 0
    messages_dlq: int = 0
    last_commit_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_message_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_lag: PartitionOffsets = field(default_factory=dict)
    processing_times: list[float] = field(default_factory=list)

    def record_processing_time(self, duration: float) -> None:
        """Record processing time and maintain a rolling window."""
        self.processing_times.append(duration)
        # Keep last 1000 measurements
        if len(self.processing_times) > 1000:
            self.processing_times.pop(0)

    @property
    def avg_processing_time(self) -> float:
        """Calculate average processing time."""
        return sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0.0


class UnifiedConsumer:
    """
    Unified Kafka consumer with comprehensive features.
    
    This consumer combines the best aspects of multiple implementations
    to provide a robust, feature-rich consumer for event-driven architectures.
    """

    def __init__(self, config: ConsumerConfig) -> None:
        self.config = config
        self.consumer: AIOKafkaConsumer | None = None
        self.dlq_producer: AIOKafkaProducer | None = None
        self._schema_registry_manager = get_schema_registry()
        self.serializer = EventSerializer()

        # State management
        self._running = False
        self._paused = False
        self._consumer_task: asyncio.Task[None] | None = None
        self._metrics_task: asyncio.Task[None] | None = None

        # Handlers
        self._event_handlers: defaultdict[str, list[EventHandler]] = defaultdict(list)
        self._error_handlers: list[ErrorHandler] = []

        # Offset management
        self._messages_since_commit = 0
        self._offset_commit_lock = asyncio.Lock()
        self._partitions_paused: set[TopicPartition] = set()

        # Metrics
        self.metrics = ConsumerMetrics()

        # Circuit breaker
        self._circuit_breaker_manager = KafkaCircuitBreakerManager()
        self._circuit_breaker: KafkaCircuitBreaker | None = None

    async def start(self) -> None:
        """Start the consumer and background tasks."""
        if self._running:
            logger.warning(f"Consumer {self.config.group_id} already running")
            return

        logger.info(f"Starting unified consumer: group={self.config.group_id}")

        # Check circuit breaker
        # Initialize circuit breaker if not exists
        if self._circuit_breaker is None:
            if self.config.group_id is None:
                raise ValueError("group_id must be set")
            self._circuit_breaker = await self._circuit_breaker_manager.get_or_create_breaker(
                CircuitBreakerType.CONSUMER,
                self.config.group_id,
            )
        
        if not await self._circuit_breaker.can_proceed():
            raise RuntimeError(f"Circuit breaker open for consumer group {self.config.group_id}")

        try:
            # Initialize main consumer
            self.consumer = AIOKafkaConsumer(
                *self.config.topics,
                bootstrap_servers=self.config.bootstrap_servers,
                group_id=self.config.group_id,
                auto_offset_reset=self.config.auto_offset_reset,
                enable_auto_commit=self.config.enable_auto_commit,
                auto_commit_interval_ms=self.config.auto_commit_interval_ms,
                session_timeout_ms=self.config.session_timeout_ms,
                heartbeat_interval_ms=self.config.heartbeat_interval_ms,
                max_poll_records=self.config.max_poll_records,
                max_poll_interval_ms=self.config.max_poll_interval_ms,
            )
            await self.consumer.start()

            # Initialize DLQ producer if enabled
            if self.config.enable_dlq and self.config.dlq_topic:
                self.dlq_producer = AIOKafkaProducer(
                    bootstrap_servers=self.config.bootstrap_servers,
                    compression_type="gzip",
                    acks="all",
                    enable_idempotence=True,
                    key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
                    value_serializer=lambda v: v,
                )
                await self.dlq_producer.start()

            # Start background tasks
            self._running = True
            self._consumer_task = asyncio.create_task(self._consume_loop())
            self._metrics_task = asyncio.create_task(self._update_metrics_loop())

            # Record success
            if self._circuit_breaker:
                await self._circuit_breaker.record_success()

            logger.info(f"Unified consumer started: group={self.config.group_id}, topics={self.config.topics}")

        except Exception as e:
            logger.error(f"Failed to start consumer: {e}")
            if self._circuit_breaker:
                await self._circuit_breaker.record_failure()
            raise

    async def stop(self) -> None:
        """Stop the consumer gracefully."""
        if not self._running:
            return

        logger.info(f"Stopping unified consumer: group={self.config.group_id}")
        self._running = False

        # Cancel background tasks
        for task in [self._consumer_task, self._metrics_task]:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        # Commit final offsets
        if self.consumer:
            try:
                await self._commit_offsets()
            except Exception as e:
                logger.error(f"Failed to commit final offsets: {e}")
            await self.consumer.stop()

        # Stop DLQ producer
        if self.dlq_producer:
            await self.dlq_producer.stop()

        logger.info(f"Unified consumer stopped: group={self.config.group_id}")

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        """
        Register an event handler for a specific event type.
        
        Args:
            event_type: Event type to handle (use "*" for all events)
            handler: Async or sync callable to process events
        """
        self._event_handlers[event_type].append(handler)
        logger.info(f"Registered handler for event type: {event_type}")

    def register_error_handler(self, handler: ErrorHandler) -> None:
        """Register an error handler."""
        self._error_handlers.append(handler)
        logger.info("Registered error handler")

    async def pause(self, topic: str | None = None, partition: int | None = None) -> None:
        """Pause consumption from specific topic/partition or all."""
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        if topic and partition is not None:
            tp = TopicPartition(topic, partition)
            self.consumer.pause([tp])
            self._partitions_paused.add(tp)
            logger.info(f"Paused partition: {topic}[{partition}]")
        else:
            # Pause all
            self._paused = True
            partitions = self.consumer.assignment()
            if partitions:
                self.consumer.pause(*partitions)
                self._partitions_paused.update(partitions)
            logger.info(f"Paused consumer: {self.config.group_id}")

    async def resume(self, topic: str | None = None, partition: int | None = None) -> None:
        """Resume consumption from specific topic/partition or all."""
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        if topic and partition is not None:
            tp = TopicPartition(topic, partition)
            self.consumer.resume([tp])
            self._partitions_paused.discard(tp)
            logger.info(f"Resumed partition: {topic}[{partition}]")
        else:
            # Resume all
            self._paused = False
            if self._partitions_paused:
                self.consumer.resume(*self._partitions_paused)
                self._partitions_paused.clear()
            logger.info(f"Resumed consumer: {self.config.group_id}")

    async def seek_to_beginning(self, partitions: Sequence[TopicPartition] | None = None) -> None:
        """Seek to beginning of partitions."""
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        if partitions:
            await self.consumer.seek_to_beginning(*partitions)
        else:
            await self.consumer.seek_to_beginning()
        logger.info(f"Seeked to beginning: {partitions or 'all'}")

    async def seek_to_end(self, partitions: Sequence[TopicPartition] | None = None) -> None:
        """Seek to end of partitions."""
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        if partitions:
            await self.consumer.seek_to_end(*partitions)
        else:
            await self.consumer.seek_to_end()
        logger.info(f"Seeked to end: {partitions or 'all'}")

    async def seek_to_offset(self, topic: str, partition: int, offset: int) -> None:
        """Seek to specific offset."""
        if not self.consumer:
            raise RuntimeError("Consumer not started")

        tp = TopicPartition(topic, partition)
        self.consumer.seek(tp, offset)
        logger.info(f"Seeked to offset {offset} for {topic}[{partition}]")

    async def get_status(self) -> dict[str, Any]:
        """Get consumer status and metrics."""
        status = {
            "running": self._running,
            "paused": self._paused,
            "group_id": self.config.group_id,
            "topics": self.config.topics,
            "registered_handlers": list(self._event_handlers.keys()),
            "error_handlers": len(self._error_handlers),
            "metrics": {
                "messages_processed": self.metrics.messages_processed,
                "messages_failed": self.metrics.messages_failed,
                "messages_dlq": self.metrics.messages_dlq,
                "avg_processing_time": self.metrics.avg_processing_time,
                "total_lag": sum(self.metrics.current_lag.values()),
            }
        }

        if self.consumer and self._running:
            try:
                partitions = self.consumer.assignment()
                status["assigned_partitions"] = len(partitions)
                status["partition_details"] = [
                    f"{p.topic}-{p.partition}"
                    for p in partitions
                ]
                status["paused_partitions"] = [
                    f"{p.topic}-{p.partition}"
                    for p in self._partitions_paused
                ]
            except Exception as e:
                logger.warning(f"Failed to get consumer metadata: {e}")

        return status

    async def _consume_loop(self) -> None:
        """Main consumption loop."""
        logger.info(f"Starting consume loop for {self.config.group_id}")

        while self._running:
            try:
                # Get messages
                if not self.consumer:
                    await asyncio.sleep(1)
                    continue
                messages = await self.consumer.getmany(
                    timeout_ms=1000,
                    max_records=self.config.max_poll_records
                )

                if not messages:
                    continue

                # Process based on mode
                await self._process_messages(messages)

                # Check if we need to commit
                await self._maybe_commit_offsets()

            except Exception as e:
                logger.error(f"Error in consume loop: {e}", exc_info=True)
                if self._circuit_breaker:
                    await self._circuit_breaker.record_failure()
                await self._handle_error(e, context="consume_loop")
                await asyncio.sleep(5)

    async def _process_messages(
            self,
            messages: dict[TopicPartition, list[ConsumerRecord]]
    ) -> None:
        """Process messages based on configured mode."""
        all_records = list(chain.from_iterable(messages.values()))
        batch_size = len(all_records)

        if batch_size > 0:
            BATCH_SIZE_PROCESSED.labels(
                topic=",".join(set(r.topic for r in all_records)),
                consumer_group=self.config.group_id
            ).observe(batch_size)

        match self.config.processing_mode:
            case ProcessingMode.SEQUENTIAL:
                for record in all_records:
                    await self._process_single_message(record)

            case ProcessingMode.PARALLEL:
                tasks = [self._process_single_message(record) for record in all_records]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Parallel processing error: {result}")

            case ProcessingMode.BATCH:
                # Process as a batch - useful for bulk operations
                await self._process_batch(all_records)

    async def _process_single_message(self, record: ConsumerRecord) -> None:
        """Process a single message with full tracing and error handling."""
        start_time = time.time()
        event = None

        # Extract trace context
        trace_headers = {k: v.decode('utf-8') for k, v in (record.headers or [])}
        parent_context = extract_trace_context(trace_headers)
        token = context.attach(parent_context)

        try:
            with trace_span(
                    name=f"kafka.consume.{record.topic}",
                    kind=SpanKind.CONSUMER,
                    attributes={
                        EventAttributes.KAFKA_TOPIC: record.topic,
                        EventAttributes.KAFKA_PARTITION: record.partition,
                        EventAttributes.KAFKA_OFFSET: record.offset,
                        EventAttributes.CONSUMER_GROUP: self.config.group_id,
                        "messaging.system": "kafka",
                        "messaging.operation": "receive",
                    }
            ) as span:
                # Deserialize event
                event = await self._deserialize_event(record)

                # Add event attributes (event is always BaseEvent now)
                add_span_attributes(**{
                    EventAttributes.EVENT_TYPE: event.event_type,
                    EventAttributes.EVENT_ID: str(event.event_id),
                })

                # Get handlers
                event_type = event.event_type
                handlers = self._event_handlers[event_type] + self._event_handlers["*"]

                if not handlers:
                    logger.warning(f"No handlers for event type: {event_type}")
                    span.set_status(Status(StatusCode.ERROR, "No handlers registered"))
                    return

                # Execute handlers
                for i, handler in enumerate(handlers):
                    handler_name = handler.__qualname__
                    with trace_span(
                            name=f"handler.{handler_name}",
                            kind=SpanKind.INTERNAL,
                            attributes={
                                "handler.name": handler_name,
                                "handler.index": i,
                            }
                    ):
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event, record)
                        else:
                            await asyncio.to_thread(handler, event, record)

                # Update metrics
                duration = time.time() - start_time
                self.metrics.messages_processed += 1
                self.metrics.record_processing_time(duration)
                self.metrics.last_message_time = datetime.now(timezone.utc)
                self._messages_since_commit += 1

                # Record to Prometheus
                PROCESSING_DURATION.labels(
                    topic=record.topic,
                    event_type=event_type,
                    consumer_group=self.config.group_id
                ).observe(duration)

                EVENTS_CONSUMED.labels(
                    topic=record.topic,
                    event_type=event_type,
                    consumer_group=self.config.group_id
                ).inc()

                KAFKA_CONSUMER_BYTES_CONSUMED.labels(
                    topic=record.topic,
                    consumer_group=self.config.group_id
                ).inc(len(record.value))

                # Record successful processing
                add_span_event("message.processed", {
                    "handler_count": len(handlers),
                    "duration_ms": int(duration * 1000)
                })

        except Exception as e:
            logger.error(
                f"Failed to process message from {record.topic}[{record.partition}]@{record.offset}: {e}",
                exc_info=True
            )

            self.metrics.messages_failed += 1

            event_type = event.event_type if event else "unknown"

            EVENTS_PROCESSING_FAILED.labels(
                topic=record.topic,
                event_type=event_type,
                consumer_group=self.config.group_id,
                error_type=type(e).__name__
            ).inc()

            # Handle processing error
            await self._handle_processing_error(e, record, event)

            # Send to DLQ if configured
            if self.config.enable_dlq:
                await self._send_to_dlq(record, e, event)

        finally:
            context.detach(token)

    async def _process_batch(self, records: list[ConsumerRecord]) -> None:
        """Process multiple records as a batch."""
        # This is a simplified batch processor - extend as needed
        logger.info(f"Processing batch of {len(records)} messages")

        try:
            events = []
            for record in records:
                try:
                    event = await self._deserialize_event(record)
                    events.append((event, record))
                except Exception as e:
                    logger.error(f"Failed to deserialize record: {e}")
                    await self._send_to_dlq(record, e, None)

            # Process each event with handlers
            for event, record in events:
                event_type = getattr(event, 'event_type', 'unknown')
                handlers = self._event_handlers.get(event_type, [])
                for handler in handlers:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event, record)
                    else:
                        await asyncio.to_thread(handler, event, record)

            self.metrics.messages_processed += len(events)
            self._messages_since_commit += len(events)

        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            self.metrics.messages_failed += len(records)

    async def _deserialize_event(self, record: ConsumerRecord) -> BaseEvent:
        """Deserialize event from Kafka record.
        
        Uses the EventSerializer which handles schema registry and Avro deserialization.
        
        Returns:
            BaseEvent: Always returns a typed event
            
        Raises:
            DeserializationError: If we cannot deserialize the event
        """
        try:
            # Use the event serializer which handles schema registry
            return self.serializer.deserialize(record.value, record.topic)
        except Exception as e:
            raise DeserializationError(
                f"Failed to deserialize event from {record.topic}: {e}"
            ) from e


    async def _maybe_commit_offsets(self) -> None:
        """Commit offsets based on strategy and thresholds."""
        if self.config.offset_strategy == OffsetStrategy.AUTO_COMMIT:
            return

        should_commit = False

        # Check message count threshold
        if self._messages_since_commit >= self.config.commit_interval_messages:
            should_commit = True

        # Check time threshold
        time_since_commit = (datetime.now(timezone.utc) - self.metrics.last_commit_time).total_seconds()
        if time_since_commit >= self.config.commit_interval_seconds:
            should_commit = True

        if should_commit:
            await self._commit_offsets()

    async def _commit_offsets(self) -> None:
        """Commit current offsets."""
        if not self.consumer or self.config.offset_strategy == OffsetStrategy.AUTO_COMMIT:
            return

        async with self._offset_commit_lock:
            try:
                await self.consumer.commit()
                self._messages_since_commit = 0
                self.metrics.last_commit_time = datetime.now(timezone.utc)

                # Update committed offset metrics
                partitions = self.consumer.assignment()
                for tp in partitions:
                    offset = await self.consumer.committed(tp)
                    if offset:
                        KAFKA_CONSUMER_COMMITTED_OFFSET.labels(
                            topic=tp.topic,
                            partition=str(tp.partition),
                            consumer_group=self.config.group_id
                        ).set(offset)

                logger.debug(f"Committed offsets for consumer group: {self.config.group_id}")

            except CommitFailedError as e:
                logger.error(f"Failed to commit offsets: {e}")
                raise

    async def _send_to_dlq(
            self,
            record: ConsumerRecord,
            error: Exception,
            event: BaseEvent | dict[str, Any] | None
    ) -> None:
        """Send failed message to Dead Letter Queue."""
        if not self.dlq_producer or not self.config.dlq_topic:
            return

        try:
            # Build DLQ message
            dlq_message = {
                "original_topic": record.topic,
                "original_partition": record.partition,
                "original_offset": record.offset,
                "original_timestamp": record.timestamp,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "consumer_group": self.config.group_id,
                "retry_count": 0,
            }

            # Include event data if available
            if event:
                if isinstance(event, BaseEvent):
                    dlq_message["event"] = event.model_dump(mode="json", by_alias=True)
                else:
                    dlq_message["event"] = event

            # Include original key
            if record.key:
                dlq_message["original_key"] = record.key.decode('utf-8') if isinstance(record.key, bytes) else str(
                    record.key)

            # Prepare headers
            headers = [
                ("original_topic", record.topic.encode('utf-8')),
                ("consumer_group", (self.config.group_id or "unknown").encode('utf-8')),
                ("error_type", type(error).__name__.encode('utf-8')),
                ("failed_at", datetime.now(timezone.utc).isoformat().encode('utf-8')),
            ]

            # Send to DLQ
            await self.dlq_producer.send(
                self.config.dlq_topic,
                value=json.dumps(dlq_message).encode('utf-8'),
                key=record.key,
                headers=headers,
            )

            self.metrics.messages_dlq += 1
            logger.warning(f"Sent failed message to DLQ: {record.topic}[{record.partition}]@{record.offset}")

        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}")

    async def _handle_processing_error(
            self,
            error: Exception,
            record: ConsumerRecord,
            event: BaseEvent | dict[str, Any] | None
    ) -> None:
        """Handle processing error for a message."""
        for handler in self._error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(error, record, event)
                else:
                    await asyncio.to_thread(handler, error, record, event)
            except Exception as e:
                logger.error(f"Error handler failed: {e}")

    async def _handle_error(self, error: Exception, context: str) -> None:
        """Handle general errors."""
        for handler in self._error_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(error, None, None)  # ErrorHandler expects 3 args
                else:
                    await asyncio.to_thread(handler, error, None, None)
            except Exception as e:
                logger.error(f"Error handler failed: {e}")

    async def _update_metrics_loop(self) -> None:
        """Update consumer metrics periodically."""
        while self._running:
            try:
                await self._update_consumer_metrics()
                await asyncio.sleep(self.config.metrics_update_interval)
            except Exception as e:
                logger.error(f"Failed to update metrics: {e}")
                await asyncio.sleep(30)

    async def _update_consumer_metrics(self) -> None:
        """Update consumer lag and offset metrics."""
        if not self.consumer:
            return

        try:
            partitions = self.consumer.assignment()
            if not partitions:
                return

            # Get current positions
            positions = {}
            for tp in partitions:
                position = await self.consumer.position(tp)
                positions[tp] = position

                KAFKA_CONSUMER_OFFSET.labels(
                    topic=tp.topic,
                    partition=str(tp.partition),
                    consumer_group=self.config.group_id
                ).set(position)

            # Get end offsets
            end_offsets = await self.consumer.end_offsets(partitions)

            # Calculate and update lag
            self.metrics.current_lag.clear()
            for tp, end_offset in end_offsets.items():
                current_position = positions.get(tp, 0)
                lag = end_offset - current_position
                self.metrics.current_lag[tp] = lag

                KAFKA_CONSUMER_LAG.labels(
                    topic=tp.topic,
                    partition=str(tp.partition),
                    consumer_group=self.config.group_id
                ).set(lag)

        except Exception as e:
            logger.error(f"Failed to update consumer metrics: {e}")

    async def __aenter__(self) -> "UnifiedConsumer":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()


class ConsumerManager:
    """
    Manager for multiple consumer instances without using globals.
    
    This replaces the singleton pattern with a more explicit manager
    that can be passed around as needed.
    """

    def __init__(self) -> None:
        self._consumers: dict[str, UnifiedConsumer] = {}
        self._lock = asyncio.Lock()

    async def create_consumer(
            self,
            group_id: str,
            config: ConsumerConfig | None = None
    ) -> UnifiedConsumer:
        """Create and register a new consumer."""
        async with self._lock:
            if group_id in self._consumers:
                raise ValueError(f"Consumer with group_id '{group_id}' already exists")

            if config is None:
                config = ConsumerConfig(group_id=group_id)
            elif config.group_id != group_id:
                raise ValueError("group_id mismatch between parameter and config")

            consumer = UnifiedConsumer(config)
            self._consumers[group_id] = consumer
            return consumer

    async def get_consumer(self, group_id: str) -> UnifiedConsumer | None:
        """Get consumer by group ID."""
        return self._consumers.get(group_id)

    async def remove_consumer(self, group_id: str) -> None:
        """Remove and stop a consumer."""
        async with self._lock:
            consumer = self._consumers.pop(group_id, None)
            if consumer:
                await consumer.stop()

    async def stop_all(self) -> None:
        """Stop all managed consumers."""
        async with self._lock:
            tasks = [consumer.stop() for consumer in self._consumers.values()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._consumers.clear()

    def list_consumers(self) -> list[str]:
        """List all consumer group IDs."""
        return list(self._consumers.keys())

    async def get_all_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all consumers."""
        status = {}
        for group_id, consumer in self._consumers.items():
            status[group_id] = await consumer.get_status()
        return status


# Convenience functions for creating consumers without managers
@asynccontextmanager
async def create_consumer(
        group_id: str,
        topics: list[str],
        handlers: dict[str, EventHandler] | None = None,
        config: ConsumerConfig | None = None
) -> AsyncIterator[UnifiedConsumer]:
    """
    Create a consumer with handlers in a context manager.
    
    Example:
        async with create_consumer("my-group", ["events"], handlers={"user.created": handle_user}) as consumer:
            # Consumer is running
            await asyncio.sleep(60)
        # Consumer is stopped
    """
    if config is None:
        config = ConsumerConfig(group_id=group_id, topics=topics)
    else:
        # Override group_id and topics
        object.__setattr__(config, "group_id", group_id)
        object.__setattr__(config, "topics", topics)

    consumer = UnifiedConsumer(config)

    # Register handlers
    if handlers:
        for event_type, handler in handlers.items():
            consumer.register_handler(event_type, handler)

    await consumer.start()
    try:
        yield consumer
    finally:
        await consumer.stop()


