from datetime import datetime, timezone
from typing import Callable

import structlog
from faststream.kafka import KafkaBroker

from app.core.metrics import DLQMetrics
from app.db.repositories import DLQRepository
from app.dlq.models import (
    DLQBatchRetryResult,
    DLQMessage,
    DLQMessageStatus,
    DLQMessageUpdate,
    DLQRetryResult,
    RetryPolicy,
    RetryStrategy,
    retry_policy_for,
)
from app.domain.enums import EventType
from app.domain.events import (
    DLQMessageDiscardedEvent,
    DLQMessageReceivedEvent,
    DLQMessageRetriedEvent,
    EventMetadata,
)
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
        logger: structlog.stdlib.BoundLogger,
        dlq_metrics: DLQMetrics,
        repository: DLQRepository,
        filters: list[Callable[[DLQMessage], bool]] | None = None,
    ):
        self.settings = settings
        self._broker = broker
        self.logger = logger
        self.metrics = dlq_metrics
        self.repository = repository
        self._retry_overrides: dict[str, RetryPolicy] = {}

        self._filters: list[Callable[[DLQMessage], bool]] = filters if filters is not None else [
            f for f in [
                None if settings.TESTING else self._filter_test_events,
                self._filter_old_messages,
            ] if f is not None
        ]


    def _filter_test_events(self, message: DLQMessage) -> bool:
        return not message.event.event_id.startswith("test-")

    def _filter_old_messages(self, message: DLQMessage) -> bool:
        max_age_days = 7
        age_seconds = (datetime.now(timezone.utc) - message.failed_at).total_seconds()
        return age_seconds < (max_age_days * 24 * 3600)

    def _resolve_retry_policy(self, message: DLQMessage) -> RetryPolicy:
        if message.original_topic in self._retry_overrides:
            return self._retry_overrides[message.original_topic]
        return retry_policy_for(message.event.event_type)

    async def process_monitoring_cycle(self) -> None:
        """Process due retries and update queue metrics. Called by APScheduler."""
        await self.process_due_retries()
        await self.update_queue_metrics()

    async def handle_message(self, message: DLQMessage) -> None:
        """Process a single DLQ message: filter -> store -> decide retry/discard."""
        for filter_func in self._filters:
            if not filter_func(message):
                self.logger.info("Message filtered out", event_id=message.event.event_id)
                return

        message.status = DLQMessageStatus.PENDING
        message.last_updated = datetime.now(timezone.utc)
        await self.repository.save_message(message)

        await self._broker.publish(
            DLQMessageReceivedEvent(
                dlq_event_id=message.event.event_id,
                original_topic=message.original_topic,
                original_event_type=message.event.event_type,
                error=message.error,
                retry_count=message.retry_count,
                producer_id=message.producer_id,
                failed_at=message.failed_at,
                metadata=EventMetadata(
                    service_name="dlq-manager",
                    service_version="1.0.0",
                    user_id=message.event.metadata.user_id,
                ),
            ),
            topic=EventType.DLQ_MESSAGE_RECEIVED,
        )

        retry_policy = self._resolve_retry_policy(message)

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
        """Retry a DLQ message by republishing to the original topic.

        FastStream handles JSON serialization of Pydantic models natively.
        """
        await self._broker.publish(
            message=message.event,
            topic=message.original_topic,
            key=message.event.event_id.encode(),
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

        await self._broker.publish(
            DLQMessageRetriedEvent(
                dlq_event_id=message.event.event_id,
                original_topic=message.original_topic,
                original_event_type=message.event.event_type,
                retry_count=new_retry_count,
                retry_topic=message.original_topic,
                metadata=EventMetadata(
                    service_name="dlq-manager",
                    service_version="1.0.0",
                    user_id=message.event.metadata.user_id,
                ),
            ),
            topic=EventType.DLQ_MESSAGE_RETRIED,
        )
        self.logger.info("Successfully retried message", event_id=message.event.event_id)

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

        await self._broker.publish(
            DLQMessageDiscardedEvent(
                dlq_event_id=message.event.event_id,
                original_topic=message.original_topic,
                original_event_type=message.event.event_type,
                reason=reason,
                retry_count=message.retry_count,
                metadata=EventMetadata(
                    service_name="dlq-manager",
                    service_version="1.0.0",
                    user_id=message.event.metadata.user_id,
                ),
            ),
            topic=EventType.DLQ_MESSAGE_DISCARDED,
        )
        self.logger.warning("Discarded message", event_id=message.event.event_id, reason=reason)

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
        self._retry_overrides[topic] = policy

    async def retry_message_manually(self, event_id: str) -> bool:
        message = await self.repository.get_message_by_id(event_id)
        if not message:
            self.logger.error("Message not found in DLQ", event_id=event_id)
            return False

        if message.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self.logger.info("Skipping manual retry", event_id=event_id, status=message.status)
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
                self.metrics.record_dlq_processing_error("batch_retry", "unknown", type(e).__name__)
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
            self.logger.error("Message not found in DLQ", event_id=event_id)
            return False

        if message.status in {DLQMessageStatus.DISCARDED, DLQMessageStatus.RETRIED}:
            self.logger.info("Skipping manual discard", event_id=event_id, status=message.status)
            return False

        await self.discard_message(message, reason)
        return True
