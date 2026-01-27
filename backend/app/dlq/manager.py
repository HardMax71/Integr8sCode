from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer
from opentelemetry.trace import SpanKind

from app.core.metrics import DLQMetrics
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
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import (
    DLQMessageDiscardedEvent,
    DLQMessageReceivedEvent,
    DLQMessageRetriedEvent,
    EventMetadata,
)
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings


class DLQManager:
    """Stateless DLQ manager - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    Worker entrypoint handles the consume loop.
    """

    def __init__(
        self,
        settings: Settings,
        producer: AIOKafkaProducer,
        schema_registry: SchemaRegistryManager,
        logger: logging.Logger,
        dlq_metrics: DLQMetrics,
        dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
        retry_topic_suffix: str = "-retry",
    ) -> None:
        self._settings = settings
        self._producer = producer
        self._schema_registry = schema_registry
        self._logger = logger
        self._metrics = dlq_metrics
        self._dlq_topic = dlq_topic
        self._retry_topic_suffix = retry_topic_suffix
        self._default_retry_policy = RetryPolicy(
            topic=KafkaTopic.DEAD_LETTER_QUEUE, strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )
        self._retry_policies: dict[KafkaTopic, RetryPolicy] = {}
        self._filters: list[object] = []
        self._dlq_events_topic = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DLQ_EVENTS}"
        self._event_metadata = EventMetadata(service_name="dlq-manager", service_version="1.0.0", user_id="system")

    def set_retry_policy(self, topic: KafkaTopic, policy: RetryPolicy) -> None:
        """Set retry policy for a specific topic."""
        self._retry_policies[topic] = policy

    def set_default_retry_policy(self, policy: RetryPolicy) -> None:
        """Set the default retry policy."""
        self._default_retry_policy = policy

    def add_filter(self, filter_func: object) -> None:
        """Add a message filter."""
        self._filters.append(filter_func)

    async def handle_dlq_message(self, raw_message: bytes, headers: dict[str, str]) -> None:
        """Handle a DLQ message from Kafka.

        Called by worker entrypoint for each message from consume loop.
        """
        start = asyncio.get_running_loop().time()

        data = json.loads(raw_message)
        dlq_msg = DLQMessage(**data, headers=headers)

        self._metrics.record_dlq_message_received(dlq_msg.original_topic, dlq_msg.event.event_type)
        self._metrics.record_dlq_message_age(
            (datetime.now(timezone.utc) - dlq_msg.failed_at).total_seconds()
        )

        ctx = extract_trace_context(dlq_msg.headers)
        with get_tracer().start_as_current_span(
            name="dlq.consume",
            context=ctx,
            kind=SpanKind.CONSUMER,
            attributes={
                EventAttributes.KAFKA_TOPIC: str(self._dlq_topic),
                EventAttributes.EVENT_TYPE: dlq_msg.event.event_type,
                EventAttributes.EVENT_ID: dlq_msg.event.event_id,
            },
        ):
            await self._process_dlq_message(dlq_msg)

        self._metrics.record_dlq_processing_duration(
            asyncio.get_running_loop().time() - start, "process"
        )

    async def _process_dlq_message(self, message: DLQMessage) -> None:
        """Process a DLQ message."""
        for filter_func in self._filters:
            if not filter_func(message):  # type: ignore[operator]
                self._logger.info("Message filtered out", extra={"event_id": message.event.event_id})
                return

        await self._store_message(message)

        retry_policy = self._retry_policies.get(message.original_topic, self._default_retry_policy)

        if not retry_policy.should_retry(message):
            await self._discard_message(message, "max_retries_exceeded")
            return

        next_retry = retry_policy.get_next_retry_time(message)

        await self._update_message_status(
            message.event.event_id,
            DLQMessageUpdate(status=DLQMessageStatus.SCHEDULED, next_retry_at=next_retry),
        )

        if retry_policy.strategy == RetryStrategy.IMMEDIATE:
            await self._retry_message(message)

    async def _store_message(self, message: DLQMessage) -> None:
        """Store DLQ message in MongoDB."""
        message.status = DLQMessageStatus.PENDING
        message.last_updated = datetime.now(timezone.utc)

        doc = DLQMessageDocument(**message.model_dump())

        existing = await DLQMessageDocument.find_one({"event.event_id": message.event.event_id})
        if existing:
            doc.id = existing.id
        await doc.save()

        await self._emit_message_received_event(message)

    async def _update_message_status(self, event_id: str, update: DLQMessageUpdate) -> None:
        """Update DLQ message status."""
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            return

        updates = {k: v for k, v in vars(update).items() if v is not None}
        updates["last_updated"] = datetime.now(timezone.utc)
        await doc.set(updates)

    async def _retry_message(self, message: DLQMessage) -> None:
        """Retry a DLQ message."""
        retry_topic = f"{message.original_topic}{self._retry_topic_suffix}"

        hdrs: dict[str, str] = {
            "dlq_retry_count": str(message.retry_count + 1),
            "dlq_original_error": message.error,
            "dlq_retry_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        hdrs = inject_trace_context(hdrs)
        kafka_headers: list[tuple[str, bytes]] = [(k, v.encode()) for k, v in hdrs.items()]

        event = message.event

        await self._producer.send_and_wait(
            topic=retry_topic,
            value=json.dumps(event.model_dump(mode="json")).encode(),
            key=message.event.event_id.encode(),
            headers=kafka_headers,
        )

        await self._producer.send_and_wait(
            topic=message.original_topic,
            value=json.dumps(event.model_dump(mode="json")).encode(),
            key=message.event.event_id.encode(),
            headers=kafka_headers,
        )

        self._metrics.record_dlq_message_retried(message.original_topic, message.event.event_type, "success")

        new_retry_count = message.retry_count + 1

        await self._update_message_status(
            message.event.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.RETRIED,
                retried_at=datetime.now(timezone.utc),
                retry_count=new_retry_count,
            ),
        )

        await self._emit_message_retried_event(message, retry_topic, new_retry_count)

        self._logger.info("Successfully retried message", extra={"event_id": message.event.event_id})

    async def _discard_message(self, message: DLQMessage, reason: str) -> None:
        """Discard a DLQ message."""
        self._metrics.record_dlq_message_discarded(message.original_topic, message.event.event_type, reason)

        await self._update_message_status(
            message.event.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.DISCARDED,
                discarded_at=datetime.now(timezone.utc),
                discard_reason=reason,
            ),
        )

        await self._emit_message_discarded_event(message, reason)

        self._logger.warning("Discarded message", extra={"event_id": message.event.event_id, "reason": reason})

    async def check_scheduled_retries(self, batch_size: int = 100) -> int:
        """Check for scheduled messages ready for retry.

        Should be called periodically from worker entrypoint.
        Returns number of messages retried.
        """
        now = datetime.now(timezone.utc)

        docs = (
            await DLQMessageDocument.find(
                {
                    "status": DLQMessageStatus.SCHEDULED,
                    "next_retry_at": {"$lte": now},
                }
            )
            .limit(batch_size)
            .to_list()
        )

        count = 0
        for doc in docs:
            message = DLQMessage.model_validate(doc, from_attributes=True)
            await self._retry_message(message)
            count += 1

        await self._update_queue_metrics()

        return count

    async def _update_queue_metrics(self) -> None:
        """Update queue size metrics."""
        pipeline: list[dict[str, object]] = [
            {"$match": {"status": {"$in": [DLQMessageStatus.PENDING, DLQMessageStatus.SCHEDULED]}}},
            {"$group": {"_id": "$original_topic", "count": {"$sum": 1}}},
        ]

        async for result in DLQMessageDocument.aggregate(pipeline):
            self._metrics.update_dlq_queue_size(result["_id"], result["count"])

    async def _emit_message_received_event(self, message: DLQMessage) -> None:
        """Emit a DLQMessageReceivedEvent."""
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

    async def _emit_message_retried_event(
        self, message: DLQMessage, retry_topic: str, new_retry_count: int
    ) -> None:
        """Emit a DLQMessageRetriedEvent."""
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
        """Emit a DLQMessageDiscardedEvent."""
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
        """Produce a DLQ lifecycle event."""
        try:
            serialized = await self._schema_registry.serialize_event(event)
            await self._producer.send_and_wait(
                topic=self._dlq_events_topic,
                value=serialized,
                key=event.event_id.encode(),
            )
        except Exception as e:
            self._logger.error(f"Failed to emit DLQ event {event.event_type}: {e}")

    async def retry_message_manually(self, event_id: str) -> bool:
        """Manually retry a DLQ message."""
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            self._logger.error("Message not found in DLQ", extra={"event_id": event_id})
            return False

        if doc.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self._logger.info("Skipping manual retry", extra={"event_id": event_id, "status": doc.status})
            return False

        message = DLQMessage.model_validate(doc, from_attributes=True)
        await self._retry_message(message)
        return True

    async def retry_messages_batch(self, event_ids: list[str]) -> DLQBatchRetryResult:
        """Retry multiple DLQ messages in batch."""
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
                self._logger.error(f"Error retrying message {event_id}: {e}")
                failed += 1
                details.append(DLQRetryResult(event_id=event_id, status="failed", error=str(e)))

        return DLQBatchRetryResult(total=len(event_ids), successful=successful, failed=failed, details=details)

    async def discard_message_manually(self, event_id: str, reason: str) -> bool:
        """Manually discard a DLQ message."""
        doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
        if not doc:
            self._logger.error("Message not found in DLQ", extra={"event_id": event_id})
            return False

        if doc.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self._logger.info("Skipping manual discard", extra={"event_id": event_id, "status": doc.status})
            return False

        message = DLQMessage.model_validate(doc, from_attributes=True)
        await self._discard_message(message, reason)
        return True

