import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from faststream.kafka import KafkaBroker

from app.core.metrics import DLQMetrics
from app.core.tracing.utils import inject_trace_context
from app.db.repositories.dlq_repository import DLQRepository
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
    """Stateless DLQ message handler.

    Pure handler — no lifecycle management, no background tasks, no consumer ownership.
    Kafka consumer loop and retry scheduling are managed externally by the worker.
    Producer is injected (already started) via DI; its lifecycle is the provider's concern.
    """

    def __init__(
        self,
        settings: Settings,
        broker: KafkaBroker,
        schema_registry: SchemaRegistryManager,
        logger: logging.Logger,
        dlq_metrics: DLQMetrics,
        repository: DLQRepository,
        dlq_topic: KafkaTopic = KafkaTopic.DEAD_LETTER_QUEUE,
        retry_topic_suffix: str = "-retry",
        default_retry_policy: RetryPolicy | None = None,
        retry_policies: dict[str, RetryPolicy] | None = None,
        filters: list[Callable[[DLQMessage], bool]] | None = None,
    ):
        self.settings = settings
        self._broker = broker
        self.schema_registry = schema_registry
        self.logger = logger
        self.metrics = dlq_metrics
        self.repository = repository
        self.dlq_topic = dlq_topic
        self.retry_topic_suffix = retry_topic_suffix
        self.default_retry_policy = default_retry_policy or RetryPolicy(
            topic="default", strategy=RetryStrategy.EXPONENTIAL_BACKOFF
        )

        self._retry_policies: dict[str, RetryPolicy] = dict(retry_policies or {})
        self._filters: list[Callable[[DLQMessage], bool]] = list(filters or [])

        self._dlq_events_topic = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DLQ_EVENTS}"
        self._event_metadata = EventMetadata(service_name="dlq-manager", service_version="1.0.0")

    def parse_kafka_message(self, msg: Any) -> DLQMessage:
        """Parse a raw Kafka ConsumerRecord into a DLQMessage."""
        data = json.loads(msg.value)
        headers = {k: v.decode() for k, v in (msg.headers or [])}
        return DLQMessage(**data, dlq_offset=msg.offset, dlq_partition=msg.partition, headers=headers)

    async def handle_message(self, message: DLQMessage) -> None:
        """Process a single DLQ message: filter → store → decide retry/discard."""
        for filter_func in self._filters:
            if not filter_func(message):
                self.logger.info("Message filtered out", extra={"event_id": message.event.event_id})
                return

        message.status = DLQMessageStatus.PENDING
        message.last_updated = datetime.now(timezone.utc)
        await self.repository.save_message(message)
        await self._emit_message_received_event(message)

        retry_policy = self._retry_policies.get(message.original_topic, self.default_retry_policy)

        if not retry_policy.should_retry(message):
            await self.discard_message(message, "max_retries_exceeded")
            return

        next_retry = retry_policy.get_next_retry_time(message)
        await self.repository.update_status(
            message.event.event_id,
            DLQMessageUpdate(status=DLQMessageStatus.SCHEDULED, next_retry_at=next_retry),
        )

        if retry_policy.strategy == RetryStrategy.IMMEDIATE:
            await self.retry_message(message)

    async def retry_message(self, message: DLQMessage) -> None:
        """Retry a DLQ message by republishing to the retry topic and original topic."""
        retry_topic = f"{message.original_topic}{self.retry_topic_suffix}"

        hdrs: dict[str, str] = {
            "dlq_retry_count": str(message.retry_count + 1),
            "dlq_original_error": message.error,
            "dlq_retry_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        hdrs = inject_trace_context(hdrs)

        event = message.event
        serialized = json.dumps(event.model_dump(mode="json")).encode()

        await self._broker.publish(
            message=serialized,
            topic=retry_topic,
            key=message.event.event_id.encode(),
            headers=hdrs,
        )
        await self._broker.publish(
            message=serialized,
            topic=message.original_topic,
            key=message.event.event_id.encode(),
            headers=hdrs,
        )

        self.metrics.record_dlq_message_retried(message.original_topic, message.event.event_type, "success")

        new_retry_count = message.retry_count + 1
        await self.repository.update_status(
            message.event.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.RETRIED,
                retried_at=datetime.now(timezone.utc),
                retry_count=new_retry_count,
            ),
        )

        await self._emit_message_retried_event(message, retry_topic, new_retry_count)
        self.logger.info("Successfully retried message", extra={"event_id": message.event.event_id})

    async def discard_message(self, message: DLQMessage, reason: str) -> None:
        """Discard a DLQ message, updating status and emitting an event."""
        self.metrics.record_dlq_message_discarded(message.original_topic, message.event.event_type, reason)

        await self.repository.update_status(
            message.event.event_id,
            DLQMessageUpdate(
                status=DLQMessageStatus.DISCARDED,
                discarded_at=datetime.now(timezone.utc),
                discard_reason=reason,
            ),
        )

        await self._emit_message_discarded_event(message, reason)
        self.logger.warning("Discarded message", extra={"event_id": message.event.event_id, "reason": reason})

    async def process_due_retries(self) -> int:
        """Process all scheduled messages whose retry time has arrived.

        Returns the number of messages retried.
        """
        messages = await self.repository.find_due_retries()
        for message in messages:
            await self.retry_message(message)
        return len(messages)

    async def update_queue_metrics(self) -> None:
        """Update queue-size metrics from MongoDB."""
        sizes = await self.repository.get_queue_sizes_by_topic()
        for topic, count in sizes.items():
            self.metrics.update_dlq_queue_size(topic, count)

    def set_retry_policy(self, topic: str, policy: RetryPolicy) -> None:
        self._retry_policies[topic] = policy

    def add_filter(self, filter_func: Callable[[DLQMessage], bool]) -> None:
        self._filters.append(filter_func)

    async def retry_message_manually(self, event_id: str) -> bool:
        message = await self.repository.get_message_by_id(event_id)
        if not message:
            self.logger.error("Message not found in DLQ", extra={"event_id": event_id})
            return False

        if message.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self.logger.info("Skipping manual retry", extra={"event_id": event_id, "status": message.status})
            return False

        await self.retry_message(message)
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
        message = await self.repository.get_message_by_id(event_id)
        if not message:
            self.logger.error("Message not found in DLQ", extra={"event_id": event_id})
            return False

        if message.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self.logger.info("Skipping manual discard", extra={"event_id": event_id, "status": message.status})
            return False

        await self.discard_message(message, reason)
        return True

    async def _emit_message_received_event(self, message: DLQMessage) -> None:
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
        try:
            serialized = await self.schema_registry.serialize_event(event)
            await self._broker.publish(
                message=serialized,
                topic=self._dlq_events_topic,
                key=event.event_id.encode(),
            )
        except Exception as e:
            self.logger.error(f"Failed to emit DLQ event {event.event_type}: {e}")
