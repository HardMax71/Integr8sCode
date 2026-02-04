import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from dishka.integrations.faststream import FromDishka
from faststream import AckPolicy, StreamMessage
from faststream.kafka import KafkaBroker
from opentelemetry.trace import SpanKind

from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer
from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessage, DLQMessageStatus
from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId, KafkaTopic
from app.domain.events.typed import (
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    DomainEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    ExecutionTimeoutEvent,
)
from app.domain.idempotency import KeyStrategy
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.idempotency import IdempotencyManager
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_service import NotificationService
from app.services.result_processor.processor import ResultProcessor
from app.services.saga import SagaOrchestrator
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


async def with_idempotency(
        event: DomainEvent,
        handler: Callable[..., Awaitable[None]],
        idem: IdempotencyManager,
        key_strategy: KeyStrategy,
        ttl_seconds: int,
        logger: logging.Logger,
) -> None:
    """Run *handler* inside an idempotency guard (check → execute → mark)."""
    result = await idem.check_and_reserve(
        event=event, key_strategy=key_strategy, ttl_seconds=ttl_seconds,
    )
    if result.is_duplicate:
        logger.info(f"Duplicate event: {event.event_type} ({event.event_id})")
        return
    try:
        await handler(event)
        await idem.mark_completed(event=event, key_strategy=key_strategy)
    except Exception as e:
        await idem.mark_failed(
            event=event, error=str(e), key_strategy=key_strategy,
        )
        raise


def _topics(settings: Settings, group_id: GroupId) -> list[str]:
    return [
        f"{settings.KAFKA_TOPIC_PREFIX}{t}"
        for t in CONSUMER_GROUP_SUBSCRIPTIONS[group_id]
    ]


def register_coordinator_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.EXECUTION_COORDINATOR),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_REQUESTED)
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_requested, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_COMPLETED)
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_completed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_FAILED)
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_failed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_CANCELLED)
    async def on_execution_cancelled(
            body: ExecutionCancelledEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_cancelled, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub
    async def on_unhandled(body: DomainEvent) -> None:
        pass


def register_k8s_worker_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.K8S_WORKER),
        group_id=GroupId.K8S_WORKER,
        ack_policy=AckPolicy.ACK,
    )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.CREATE_POD_COMMAND)
    async def on_create_pod(
            body: CreatePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, worker.handle_create_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.DELETE_POD_COMMAND)
    async def on_delete_pod(
            body: DeletePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, worker.handle_delete_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger)

    @sub
    async def on_unhandled(body: DomainEvent) -> None:
        pass


def register_result_processor_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.RESULT_PROCESSOR),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_COMPLETED)
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, processor.handle_execution_completed, idem, KeyStrategy.CONTENT_HASH, 7200, logger)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_FAILED)
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, processor.handle_execution_failed, idem, KeyStrategy.CONTENT_HASH, 7200, logger)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_TIMEOUT)
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, processor.handle_execution_timeout, idem, KeyStrategy.CONTENT_HASH, 7200, logger)

    @sub
    async def on_unhandled(body: DomainEvent) -> None:
        pass


def register_saga_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.SAGA_ORCHESTRATOR),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_REQUESTED)
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_requested(body)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_COMPLETED)
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_completed(body)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_FAILED)
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_failed(body)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_TIMEOUT)
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_timeout(body)

    @sub
    async def on_unhandled(body: DomainEvent) -> None:
        pass



def register_sse_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    @broker.subscriber(
        *_topics(settings, GroupId.WEBSOCKET_GATEWAY),
        group_id="sse-bridge-pool",
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_sse_event(
            body: DomainEvent,
            sse_bus: FromDishka[SSERedisBus],
    ) -> None:
        if body.event_type in SSERedisBus.SSE_ROUTED_EVENTS:
            await sse_bus.route_domain_event(body)


def register_notification_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.NOTIFICATION_SERVICE),
        group_id=GroupId.NOTIFICATION_SERVICE,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_COMPLETED)
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_completed(body)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_FAILED)
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_failed(body)

    @sub(filter=lambda msg: msg.headers["event_type"] == EventType.EXECUTION_TIMEOUT)
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_timeout(body)

    @sub
    async def on_unhandled(body: DomainEvent) -> None:
        pass


def register_dlq_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    """Register a DLQ subscriber that consumes dead-letter messages.

    DLQ messages are Avro-encoded DomainEvents (same as every other topic).
    DLQ metadata (original_topic, error, retry_count, etc.) lives in Kafka headers.
    """
    topic_name = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DEAD_LETTER_QUEUE}"

    @broker.subscriber(
        topic_name,
        group_id=GroupId.DLQ_MANAGER,
        ack_policy=AckPolicy.ACK,
        auto_offset_reset="earliest",
    )
    async def on_dlq_message(
            body: DomainEvent,
            msg: StreamMessage[Any],
            manager: FromDishka[DLQManager],
            logger: FromDishka[logging.Logger],
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
                EventAttributes.EVENT_TYPE: body.event_type,
                EventAttributes.EVENT_ID: body.event_id,
            },
        ):
            await manager.handle_message(dlq_msg)

        manager.metrics.record_dlq_message_received(dlq_msg.original_topic, body.event_type)
        manager.metrics.record_dlq_message_age(
            (datetime.now(timezone.utc) - dlq_msg.failed_at).total_seconds()
        )
        manager.metrics.record_dlq_processing_duration(
            asyncio.get_running_loop().time() - start, "process"
        )
