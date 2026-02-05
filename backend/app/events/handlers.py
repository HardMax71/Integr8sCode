"""Kafka event handlers.

Architecture: 1 topic = 1 event type.
- Topic name derived from class: ExecutionRequestedEvent -> execution_requested
- No filters needed - topic IS the router
- Type hint = deserialization contract
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from dishka.integrations.faststream import FromDishka
from faststream import AckPolicy, Context
from faststream.kafka import KafkaBroker
from faststream.message import StreamMessage
from opentelemetry.trace import SpanKind

from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessage, DLQMessageStatus
from app.domain.enums.kafka import GroupId
from app.domain.events.typed import (
    BaseEvent,
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    ExecutionTimeoutEvent,
)
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_service import NotificationService
from app.services.result_processor.processor import ResultProcessor
from app.services.saga import SagaOrchestrator
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


def register_coordinator_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    prefix = settings.KAFKA_TOPIC_PREFIX

    @broker.subscriber(
        ExecutionRequestedEvent.topic(prefix),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_requested(
        body: ExecutionRequestedEvent,
        coordinator: FromDishka[ExecutionCoordinator],
    ) -> None:
        await coordinator.handle_execution_requested(body)

    @broker.subscriber(
        ExecutionCompletedEvent.topic(prefix),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_completed(
        body: ExecutionCompletedEvent,
        coordinator: FromDishka[ExecutionCoordinator],
    ) -> None:
        await coordinator.handle_execution_completed(body)

    @broker.subscriber(
        ExecutionFailedEvent.topic(prefix),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_failed(
        body: ExecutionFailedEvent,
        coordinator: FromDishka[ExecutionCoordinator],
    ) -> None:
        await coordinator.handle_execution_failed(body)

    @broker.subscriber(
        ExecutionCancelledEvent.topic(prefix),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_cancelled(
        body: ExecutionCancelledEvent,
        coordinator: FromDishka[ExecutionCoordinator],
    ) -> None:
        await coordinator.handle_execution_cancelled(body)


def register_k8s_worker_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    prefix = settings.KAFKA_TOPIC_PREFIX

    @broker.subscriber(
        CreatePodCommandEvent.topic(prefix),
        group_id=GroupId.K8S_WORKER,
        ack_policy=AckPolicy.ACK,
    )
    async def on_create_pod(
        body: CreatePodCommandEvent,
        worker: FromDishka[KubernetesWorker],
    ) -> None:
        await worker.handle_create_pod_command(body)

    @broker.subscriber(
        DeletePodCommandEvent.topic(prefix),
        group_id=GroupId.K8S_WORKER,
        ack_policy=AckPolicy.ACK,
    )
    async def on_delete_pod(
        body: DeletePodCommandEvent,
        worker: FromDishka[KubernetesWorker],
    ) -> None:
        await worker.handle_delete_pod_command(body)


def register_result_processor_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    prefix = settings.KAFKA_TOPIC_PREFIX

    @broker.subscriber(
        ExecutionCompletedEvent.topic(prefix),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_completed(
        body: ExecutionCompletedEvent,
        processor: FromDishka[ResultProcessor],
    ) -> None:
        await processor.handle_execution_completed(body)

    @broker.subscriber(
        ExecutionFailedEvent.topic(prefix),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_failed(
        body: ExecutionFailedEvent,
        processor: FromDishka[ResultProcessor],
    ) -> None:
        await processor.handle_execution_failed(body)

    @broker.subscriber(
        ExecutionTimeoutEvent.topic(prefix),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_timeout(
        body: ExecutionTimeoutEvent,
        processor: FromDishka[ResultProcessor],
    ) -> None:
        await processor.handle_execution_timeout(body)


def register_saga_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    prefix = settings.KAFKA_TOPIC_PREFIX

    @broker.subscriber(
        ExecutionRequestedEvent.topic(prefix),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_requested(
        body: ExecutionRequestedEvent,
        orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_requested(body)

    @broker.subscriber(
        ExecutionCompletedEvent.topic(prefix),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_completed(
        body: ExecutionCompletedEvent,
        orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_completed(body)

    @broker.subscriber(
        ExecutionFailedEvent.topic(prefix),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_failed(
        body: ExecutionFailedEvent,
        orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_failed(body)

    @broker.subscriber(
        ExecutionTimeoutEvent.topic(prefix),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_timeout(
        body: ExecutionTimeoutEvent,
        orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_timeout(body)


def register_sse_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    """SSE subscriber - listens to multiple event types for real-time updates."""
    prefix = settings.KAFKA_TOPIC_PREFIX

    @broker.subscriber(
        ExecutionCompletedEvent.topic(prefix),
        group_id="sse-bridge-pool",
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_completed(body: ExecutionCompletedEvent, sse_bus: FromDishka[SSERedisBus]) -> None:
        await sse_bus.route_domain_event(body)

    @broker.subscriber(
        ExecutionFailedEvent.topic(prefix),
        group_id="sse-bridge-pool",
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_failed(body: ExecutionFailedEvent, sse_bus: FromDishka[SSERedisBus]) -> None:
        await sse_bus.route_domain_event(body)

    @broker.subscriber(
        ExecutionTimeoutEvent.topic(prefix),
        group_id="sse-bridge-pool",
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_timeout(body: ExecutionTimeoutEvent, sse_bus: FromDishka[SSERedisBus]) -> None:
        await sse_bus.route_domain_event(body)

    @broker.subscriber(
        ExecutionCancelledEvent.topic(prefix),
        group_id="sse-bridge-pool",
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_cancelled(body: ExecutionCancelledEvent, sse_bus: FromDishka[SSERedisBus]) -> None:
        await sse_bus.route_domain_event(body)


def register_notification_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    prefix = settings.KAFKA_TOPIC_PREFIX

    @broker.subscriber(
        ExecutionCompletedEvent.topic(prefix),
        group_id=GroupId.NOTIFICATION_SERVICE,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )
    async def on_execution_completed(
        body: ExecutionCompletedEvent,
        service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_completed(body)

    @broker.subscriber(
        ExecutionFailedEvent.topic(prefix),
        group_id=GroupId.NOTIFICATION_SERVICE,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )
    async def on_execution_failed(
        body: ExecutionFailedEvent,
        service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_failed(body)

    @broker.subscriber(
        ExecutionTimeoutEvent.topic(prefix),
        group_id=GroupId.NOTIFICATION_SERVICE,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )
    async def on_execution_timeout(
        body: ExecutionTimeoutEvent,
        service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_timeout(body)


def register_dlq_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    """Register a DLQ subscriber that consumes dead-letter messages.

    DLQ messages are stored with topic metadata in headers for replay routing.
    """
    dlq_topic = f"{settings.KAFKA_TOPIC_PREFIX}dead_letter_queue"

    @broker.subscriber(
        dlq_topic,
        group_id=GroupId.DLQ_MANAGER,
        ack_policy=AckPolicy.ACK,
        auto_offset_reset="earliest",
    )
    async def on_dlq_message(
        body: BaseEvent,
        manager: FromDishka[DLQManager],
        logger: FromDishka[logging.Logger],
        msg: StreamMessage[Any] = Context("message"),
    ) -> None:
        start = asyncio.get_running_loop().time()
        raw = msg.raw_message
        headers = {k: v.decode() for k, v in (raw.headers or [])}

        dlq_msg = DLQMessage(
            event=body,
            original_topic=headers.get("original_topic", ""),
            error=headers.get("error", "Unknown error"),
            retry_count=int(headers.get("retry_count", "0")),
            failed_at=datetime.fromisoformat(headers["failed_at"]),
            status=DLQMessageStatus(headers.get("status", "pending")),
            producer_id=headers.get("producer_id", "unknown"),
            dlq_offset=raw.offset,
            dlq_partition=raw.partition,
            headers=headers,
        )

        ctx = extract_trace_context(headers)
        with get_tracer().start_as_current_span(
            name="dlq.consume",
            context=ctx,
            kind=SpanKind.CONSUMER,
            attributes={
                EventAttributes.KAFKA_TOPIC: str(manager.dlq_topic),
                EventAttributes.EVENT_ID: body.event_id,
            },
        ):
            await manager.handle_message(dlq_msg)

        manager.metrics.record_dlq_message_received(dlq_msg.original_topic, type(body).__name__)
        manager.metrics.record_dlq_message_age(
            (datetime.now(timezone.utc) - dlq_msg.failed_at).total_seconds()
        )
        manager.metrics.record_dlq_processing_duration(
            asyncio.get_running_loop().time() - start, "process"
        )
