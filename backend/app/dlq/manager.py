import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from opentelemetry.trace import SpanKind

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics.context import get_dlq_metrics
from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer, inject_trace_context
from app.db.docs import DLQMessageDocument
from app.dlq.models import (
    DLQBatchRetryResult,
    DLQMessage,
    DLQMessageStatus,
    DLQMessageUpdate,
    DLQRetryResult,
    RetryPolicy,
    RetryStrategy,
)
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.events.typed import (
    DLQMessageDiscardedEvent,
    DLQMessageReceivedEvent,
    DLQMessageRetriedEvent,
    EventMetadata,
)
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings


class DLQManager(LifecycleEnabled):
    def __init__(
        self,
        settings: Settings,
        consumer: AIOKafkaConsumer,
        producer: AIOKafkaProducer,
        schema_registry: SchemaRegistryManager,
        logger: logging.Logger,
        dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
        retry_topic_suffix: str = "-retry",
        default_retry_policy: RetryPolicy | None = None,
    ):
        super().__init__()
        self.settings = settings
        self.metrics = get_dlq_metrics()
        self.schema_registry = schema_registry
        self.logger = logger
        self.dlq_topic = dlq_topic
        self.retry_topic_suffix = retry_topic_suffix
        self.default_retry_policy = default_retry_policy or RetryPolicy(
            topic="default", strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )
        self.consumer: AIOKafkaConsumer = consumer
        self.producer: AIOKafkaProducer = producer

        self._process_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None

        # Topic-specific retry policies
        self._retry_policies: dict[str, RetryPolicy] = {}

        # Message filters
        self._filters: list[Callable[[DLQMessage], bool]] = []

        self._dlq_events_topic = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DLQ_EVENTS}"
        self._event_metadata = EventMetadata(service_name="dlq-manager", service_version="1.0.0")

    def _kafka_msg_to_message(self, msg: Any) -> DLQMessage:
        """Parse Kafka ConsumerRecord into DLQMessage."""
        data = json.loads(msg.value)
        headers = {k: v.decode() for k, v in (msg.headers or [])}
        return DLQMessage(**data, dlq_offset=msg.offset, dlq_partition=msg.partition, headers=headers)

    async def _on_start(self) -> None:
        """Start DLQ manager."""
        # Start producer and consumer
        await self.producer.start()
        await self.consumer.start()

        # Start processing tasks
        self._process_task = asyncio.create_task(self._process_messages())
        self._monitor_task = asyncio.create_task(self._monitor_dlq())

        self.logger.info("DLQ Manager started")

    async def _on_stop(self) -> None:
        """Stop DLQ manager."""
        # Cancel tasks
        for task in [self._process_task, self._monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop Kafka clients
        await self.consumer.stop()
        await self.producer.stop()

        self.logger.info("DLQ Manager stopped")

    async def _process_messages(self) -> None:
        """Process DLQ messages using async iteration."""
        async for msg in self.consumer:
            try:
                start = asyncio.get_running_loop().time()
                dlq_msg = self._kafka_msg_to_message(msg)

                # Record metrics
                self.metrics.record_dlq_message_received(dlq_msg.original_topic, dlq_msg.event.event_type)
                self.metrics.record_dlq_message_age((datetime.now(timezone.utc) - dlq_msg.failed_at).total_seconds())

                # Process with tracing
                ctx = extract_trace_context(dlq_msg.headers)
                with get_tracer().start_as_current_span(
                    name="dlq.consume",
                    context=ctx,
                    kind=SpanKind.CONSUMER,
                    attributes={
                        EventAttributes.KAFKA_TOPIC: self.dlq_topic,
                        EventAttributes.EVENT_TYPE: dlq_msg.event.event_type,
                        EventAttributes.EVENT_ID: dlq_msg.event.event_id,
                    },
                ):
                    await self._process_dlq_message(dlq_msg)

                # Commit and record duration
                await self.consumer.commit()
                self.metrics.record_dlq_processing_duration(asyncio.get_running_loop().time() - start, "process")

            except Exception as e:
                self.logger.error(f"Error processing DLQ message: {e}")

    async def _process_dlq_message(self, message: DLQMessage) -> None:
        # Apply filters
        for filter_func in self._filters:
            if not filter_func(message):
                self.logger.info("Message filtered out", extra={"event_id": message.event.event_id})
                return

        # Store in MongoDB via Beanie
        await self._store_message(message)

        # Get retry policy for topic
        retry_policy = self._retry_policies.get(message.original_topic, self.default_retry_policy)

        # Check if should retry
        if not retry_policy.should_retry(message):
            await self._discard_message(message, "max_retries_exceeded")
            return

        # Calculate next retry time
        next_retry = retry_policy.get_next_retry_time(message)

        # Update message status
        await self._update_message_status(
            message.event.event_id,
            DLQMessageUpdate(status=DLQMessageStatus.SCHEDULED, next_retry_at=next_retry),
        )

        # If immediate retry, process now
        if retry_policy.strategy == RetryStrategy.IMMEDIATE:
            await self._retry_message(message)

    async def _store_message(self, message: DLQMessage) -> None:
        # Ensure message has proper status and timestamps
        message.status = DLQMessageStatus.PENDING
        message.last_updated = datetime.now(timezone.utc)

        doc = DLQMessageDocument(**message.model_dump())

        # Upsert using Beanie
        existing = await DLQMessageDocument.find_one({"event.event_id": message.event.event_id})
        if existing:
            doc.id = existing.id
        await doc.save()

        await self._emit_message_received_event(message)

    async def _update_message_status(self, event_id: str, update: DLQMessageUpdate) -> None:
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            return

        update_dict: dict[str, Any] = {"status": update.status, "last_updated": datetime.now(timezone.utc)}
        if update.next_retry_at is not None:
            update_dict["next_retry_at"] = update.next_retry_at
        if update.retried_at is not None:
            update_dict["retried_at"] = update.retried_at
        if update.discarded_at is not None:
            update_dict["discarded_at"] = update.discarded_at
        if update.retry_count is not None:
            update_dict["retry_count"] = update.retry_count
        if update.discard_reason is not None:
            update_dict["discard_reason"] = update.discard_reason
        if update.last_error is not None:
            update_dict["last_error"] = update.last_error

        await doc.set(update_dict)

    async def _retry_message(self, message: DLQMessage) -> None:
        # Send to retry topic first (for monitoring)
        retry_topic = f"{message.original_topic}{self.retry_topic_suffix}"

        hdrs: dict[str, str] = {
            "dlq_retry_count": str(message.retry_count + 1),
            "dlq_original_error": message.error,
            "dlq_retry_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        hdrs = inject_trace_context(hdrs)
        kafka_headers: list[tuple[str, bytes]] = [(k, v.encode()) for k, v in hdrs.items()]

        # Get the original event
        event = message.event

        # Send to retry topic
        await self.producer.send_and_wait(
            topic=retry_topic,
            value=json.dumps(event.model_dump(mode="json")).encode(),
            key=message.event.event_id.encode(),
            headers=kafka_headers,
        )

        # Send to original topic
        await self.producer.send_and_wait(
            topic=message.original_topic,
            value=json.dumps(event.model_dump(mode="json")).encode(),
            key=message.event.event_id.encode(),
            headers=kafka_headers,
        )

        # Update metrics
        self.metrics.record_dlq_message_retried(message.original_topic, message.event.event_type, "success")

        new_retry_count = message.retry_count + 1

        # Update status
        await self._update_message_status(
            message.event.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.RETRIED,
                retried_at=datetime.now(timezone.utc),
                retry_count=new_retry_count,
            ),
        )

        # Emit DLQ message retried event
        await self._emit_message_retried_event(message, retry_topic, new_retry_count)

        self.logger.info("Successfully retried message", extra={"event_id": message.event.event_id})

    async def _discard_message(self, message: DLQMessage, reason: str) -> None:
        # Update metrics
        self.metrics.record_dlq_message_discarded(message.original_topic, message.event.event_type, reason)

        # Update status
        await self._update_message_status(
            message.event.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.DISCARDED,
                discarded_at=datetime.now(timezone.utc),
                discard_reason=reason,
            ),
        )

        await self._emit_message_discarded_event(message, reason)

        self.logger.warning("Discarded message", extra={"event_id": message.event.event_id, "reason": reason})

    async def _monitor_dlq(self) -> None:
        while self.is_running:
            try:
                # Find messages ready for retry using Beanie
                now = datetime.now(timezone.utc)

                docs = (
                    await DLQMessageDocument.find(
                        {
                            "status": DLQMessageStatus.SCHEDULED,
                            "next_retry_at": {"$lte": now},
                        }
                    )
                    .limit(100)
                    .to_list()
                )

                for doc in docs:
                    message = DLQMessage.model_validate(doc, from_attributes=True)
                    await self._retry_message(message)

                # Update queue size metrics
                await self._update_queue_metrics()

                # Sleep before next check
                await asyncio.sleep(10)

            except Exception as e:
                self.logger.error(f"Error in DLQ monitor: {e}")
                await asyncio.sleep(60)

    async def _update_queue_metrics(self) -> None:
        # Get counts by topic using Beanie aggregation
        pipeline: list[dict[str, Any]] = [
            {"$match": {"status": {"$in": [DLQMessageStatus.PENDING, DLQMessageStatus.SCHEDULED]}}},
            {"$group": {"_id": "$original_topic", "count": {"$sum": 1}}},
        ]

        async for result in DLQMessageDocument.aggregate(pipeline):
            self.metrics.update_dlq_queue_size(result["_id"], result["count"])

    def set_retry_policy(self, topic: str, policy: RetryPolicy) -> None:
        self._retry_policies[topic] = policy

    def add_filter(self, filter_func: Callable[[DLQMessage], bool]) -> None:
        self._filters.append(filter_func)

    async def _emit_message_received_event(self, message: DLQMessage) -> None:
        """Emit a DLQMessageReceivedEvent to the DLQ events topic."""
        event = DLQMessageReceivedEvent(
            dlq_event_id=message.event.event_id,
            original_topic=message.original_topic,
            original_event_type=str(message.event.event_type),
            error=message.error,
            retry_count=message.retry_count,
            producer_id=message.producer_id,
            failed_at=message.failed_at,
            metadata=self._event_metadata,
        )
        await self._produce_dlq_event(event)

    async def _emit_message_retried_event(self, message: DLQMessage, retry_topic: str, new_retry_count: int) -> None:
        """Emit a DLQMessageRetriedEvent to the DLQ events topic."""
        event = DLQMessageRetriedEvent(
            dlq_event_id=message.event.event_id,
            original_topic=message.original_topic,
            original_event_type=str(message.event.event_type),
            retry_count=new_retry_count,
            retry_topic=retry_topic,
            metadata=self._event_metadata,
        )
        await self._produce_dlq_event(event)

    async def _emit_message_discarded_event(self, message: DLQMessage, reason: str) -> None:
        """Emit a DLQMessageDiscardedEvent to the DLQ events topic."""
        event = DLQMessageDiscardedEvent(
            dlq_event_id=message.event.event_id,
            original_topic=message.original_topic,
            original_event_type=str(message.event.event_type),
            reason=reason,
            retry_count=message.retry_count,
            metadata=self._event_metadata,
        )
        await self._produce_dlq_event(event)

    async def _produce_dlq_event(
        self, event: DLQMessageReceivedEvent | DLQMessageRetriedEvent | DLQMessageDiscardedEvent
    ) -> None:
        """Produce a DLQ lifecycle event to the DLQ events topic."""
        try:
            serialized = await self.schema_registry.serialize_event(event)
            await self.producer.send_and_wait(
                topic=self._dlq_events_topic,
                value=serialized,
                key=event.event_id.encode(),
            )
        except Exception as e:
            self.logger.error(f"Failed to emit DLQ event {event.event_type}: {e}")

    async def retry_message_manually(self, event_id: str) -> bool:
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            self.logger.error("Message not found in DLQ", extra={"event_id": event_id})
            return False

        # Guard against invalid states
        if doc.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self.logger.info("Skipping manual retry", extra={"event_id": event_id, "status": doc.status})
            return False

        message = DLQMessage.model_validate(doc, from_attributes=True)
        await self._retry_message(message)
        return True

    async def retry_messages_batch(self, event_ids: list[str]) -> DLQBatchRetryResult:
        """Retry multiple DLQ messages in batch.

        Args:
            event_ids: List of event IDs to retry

        Returns:
            Batch result with success/failure counts and details
        """
        details: list[DLQRetryResult] = []
        successful = 0
        failed = 0

        for event_id in event_ids:
            try:
                success = await self.retry_message_manually(event_id)
                if success:
                    successful += 1
                    details.append(DLQRetryResult(event_id=event_id, status="success"))
                else:
                    failed += 1
                    details.append(DLQRetryResult(event_id=event_id, status="failed", error="Retry failed"))
            except Exception as e:
                self.logger.error(f"Error retrying message {event_id}: {e}")
                failed += 1
                details.append(DLQRetryResult(event_id=event_id, status="failed", error=str(e)))

        return DLQBatchRetryResult(total=len(event_ids), successful=successful, failed=failed, details=details)

    async def discard_message_manually(self, event_id: str, reason: str) -> bool:
        """Manually discard a DLQ message with state validation.

        Args:
            event_id: The event ID to discard
            reason: Reason for discarding

        Returns:
            True if discarded, False if not found or in terminal state
        """
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            self.logger.error("Message not found in DLQ", extra={"event_id": event_id})
            return False

        # Guard against invalid states (terminal states)
        if doc.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self.logger.info("Skipping manual discard", extra={"event_id": event_id, "status": doc.status})
            return False

        message = DLQMessage.model_validate(doc, from_attributes=True)
        await self._discard_message(message, reason)
        return True


def create_dlq_manager(
    settings: Settings,
    schema_registry: SchemaRegistryManager,
    logger: logging.Logger,
    dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
    retry_topic_suffix: str = "-retry",
    default_retry_policy: RetryPolicy | None = None,
) -> DLQManager:
    topic_name = f"{settings.KAFKA_TOPIC_PREFIX}{dlq_topic}"
    consumer = AIOKafkaConsumer(
        topic_name,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"{GroupId.DLQ_MANAGER}.{settings.KAFKA_GROUP_SUFFIX}",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="dlq-manager-consumer",
    )
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="dlq-manager-producer",
        acks="all",
        compression_type="gzip",
        max_batch_size=16384,
        linger_ms=10,
        enable_idempotence=True,
    )
    if default_retry_policy is None:
        default_retry_policy = RetryPolicy(topic="default", strategy=RetryStrategy.EXPONENTIAL_BACKOFF)
    return DLQManager(
        settings=settings,
        consumer=consumer,
        producer=producer,
        schema_registry=schema_registry,
        logger=logger,
        dlq_topic=dlq_topic,
        retry_topic_suffix=retry_topic_suffix,
        default_retry_policy=default_retry_policy,
    )
