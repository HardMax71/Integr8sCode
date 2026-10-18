from datetime import datetime, timezone
from typing import Callable

import structlog
from faststream.kafka import KafkaBroker
from opentelemetry import trace

from app.db import DLQRepository
from app.dlq.models import (
    DLQ_GROUP_HEADER,
    DLQ_RETRY_HEADER,
    DLQMessage,
    DLQMessageStatus,
    DLQMessageUpdate,
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
from app.events import PRODUCE_ERRORS
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
        tracer: trace.Tracer,
        repository: DLQRepository,
        filters: list[Callable[[DLQMessage], bool]] | None = None,
    ):
        self.settings = settings
        self._broker = broker
        self.logger = logger
        self._tracer = tracer
        self.repository = repository

        self._filters: list[Callable[[DLQMessage], bool]] = (
            filters
            if filters is not None
            else [
                f
                for f in [
                    None if settings.ENVIRONMENT == "test" else self._filter_test_events,
                    self._filter_old_messages,
                ]
                if f is not None
            ]
        )

    def _filter_test_events(self, message: DLQMessage) -> bool:
        return not message.event.event_id.startswith("test-")

    def _filter_old_messages(self, message: DLQMessage) -> bool:
        max_age_days = 7
        age_seconds = (datetime.now(timezone.utc) - message.failed_at).total_seconds()
        return age_seconds < (max_age_days * 24 * 3600)

    async def process_monitoring_cycle(self) -> None:
        """Process due retries and report the DLQ size per topic. Called by APScheduler."""
        with self._tracer.start_as_current_span("dlq.monitoring_cycle"):
            await self.process_due_retries()
            await self.report_queue_sizes()

    async def handle_message(self, message: DLQMessage) -> None:
        """Process a single DLQ message: filter -> store -> decide retry/discard."""
        attributes = {
            "dlq.operation": "handle",
            "dlq.original_topic": message.original_topic,
            "dlq.event_type": message.event.event_type,
        }
        with self._tracer.start_as_current_span("dlq.handle", attributes=attributes) as span:
            for filter_func in self._filters:
                if not filter_func(message):
                    self.logger.info("Message filtered out", event_id=message.event.event_id)
                    span.set_attribute("dlq.outcome", "filtered")
                    return

            message.status = DLQMessageStatus.PENDING
            message.last_updated = datetime.now(timezone.utc)
            await self.repository.save_message(message)
            age_seconds = (datetime.now(timezone.utc) - message.failed_at).total_seconds()
            span.set_attributes({"dlq.outcome": "stored", "dlq.message_age_seconds": age_seconds})

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

            retry_policy = retry_policy_for(message.event.event_type)

            if not retry_policy.should_retry(message):
                await self.discard_message(message, "max_retries_exceeded")
                return

            next_retry = retry_policy.get_next_retry_time(message)
            await self.repository.update_status(
                message.event.event_id,
                message.consumer_group,
                DLQMessageUpdate(status=DLQMessageStatus.SCHEDULED, next_retry_at=next_retry),
            )

            if retry_policy.strategy == RetryStrategy.IMMEDIATE:
                await self.retry_message(message)

    async def retry_message(self, message: DLQMessage) -> None:
        """Republish a DLQ message to its original topic for the consumer group that failed on it.

        Every group subscribed to the topic receives the event again, and the headers tell all
        but the failed group to skip it. A retry that fails again comes back with its retry count.
        """
        attributes = {
            "dlq.operation": "retry",
            "dlq.original_topic": message.original_topic,
            "dlq.event_type": message.event.event_type,
        }
        with self._tracer.start_as_current_span("dlq.retry", attributes=attributes) as span:
            new_retry_count = message.retry_count + 1
            # Mark it before publishing: a retry that fails fast saves its new failure over this row
            await self.repository.update_status(
                message.event.event_id,
                message.consumer_group,
                DLQMessageUpdate(
                    status=DLQMessageStatus.RETRIED,
                    retried_at=datetime.now(timezone.utc),
                    retry_count=new_retry_count,
                ),
            )
            try:
                await self._broker.publish(
                    message=message.event,
                    topic=message.original_topic,
                    key=message.event.event_id.encode(),
                    headers={DLQ_GROUP_HEADER: message.consumer_group, DLQ_RETRY_HEADER: str(new_retry_count)},
                )
            except PRODUCE_ERRORS as e:
                span.set_attributes({"dlq.retry_result": "failed", "dlq.error_type": type(e).__name__})
                await self.repository.update_status(
                    message.event.event_id,
                    message.consumer_group,
                    DLQMessageUpdate(status=DLQMessageStatus.SCHEDULED, retry_count=message.retry_count),
                )
                raise
            span.set_attribute("dlq.retry_result", "success")

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
        attributes = {
            "dlq.operation": "discard",
            "dlq.original_topic": message.original_topic,
            "dlq.event_type": message.event.event_type,
            "dlq.discard_reason": reason,
        }
        with self._tracer.start_as_current_span("dlq.discard", attributes=attributes):
            await self.repository.update_status(
                message.event.event_id,
                message.consumer_group,
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

    async def report_queue_sizes(self) -> None:
        """Report each topic's DLQ size on its own span, which the collector keeps as a gauge."""
        sizes = await self.repository.get_queue_sizes_by_topic()
        for topic, count in sizes.items():
            self._tracer.start_span("dlq.queue_size", attributes={"dlq.original_topic": topic, "dlq.size": count}).end()
