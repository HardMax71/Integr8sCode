import dataclasses
from collections.abc import Awaitable, Callable

import structlog
from dishka.integrations.faststream import FromDishka
from faststream import AckPolicy
from faststream.kafka import KafkaBroker

from app.core.metrics import EventMetrics
from app.domain.enums import EventType
from app.domain.events import (
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
from app.domain.sse import SSEExecutionEventData
from app.services.idempotency import IdempotencyManager
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_service import NotificationService
from app.services.result_processor import ResultProcessor
from app.services.saga import SagaOrchestrator
from app.services.sse import SSERedisBus
from app.settings import Settings

_sse_field_names: frozenset[str] = frozenset(f.name for f in dataclasses.fields(SSEExecutionEventData))


async def _track_consumed(
        metrics: EventMetrics, event: DomainEvent, consumer_group: str, coro: Awaitable[None],
) -> None:
    """Record consumption metric, await *coro*, and record failure metric on error."""
    metrics.record_kafka_message_consumed(topic=event.event_type, consumer_group=consumer_group)
    try:
        await coro
    except Exception as e:
        metrics.record_events_processing_failed(
            topic=event.event_type, event_type=event.event_type,
            consumer_group=consumer_group, error_type=type(e).__name__,
        )
        metrics.record_kafka_consumption_error(
            topic=event.event_type, consumer_group=consumer_group, error_type=type(e).__name__,
        )
        raise


# --8<-- [start:with_idempotency]
async def with_idempotency(
        event: DomainEvent,
        handler: Callable[..., Awaitable[None]],
        idem: IdempotencyManager,
        key_strategy: KeyStrategy,
        ttl_seconds: int,
        logger: structlog.stdlib.BoundLogger,
) -> None:
    """Run *handler* inside an idempotency guard (check -> execute -> mark)."""
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
# --8<-- [end:with_idempotency]


def register_k8s_worker_subscriber(broker: KafkaBroker) -> None:
    @broker.subscriber(
        EventType.CREATE_POD_COMMAND,
        group_id="k8s-worker",
        ack_policy=AckPolicy.ACK,
    )
    async def on_create_pod(
            body: CreatePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "k8s-worker",
            with_idempotency(body, worker.handle_create_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger))

    @broker.subscriber(
        EventType.DELETE_POD_COMMAND,
        group_id="k8s-worker",
        ack_policy=AckPolicy.ACK,
    )
    async def on_delete_pod(
            body: DeletePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "k8s-worker",
            with_idempotency(body, worker.handle_delete_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger))


def register_result_processor_subscriber(broker: KafkaBroker) -> None:
    @broker.subscriber(
        EventType.EXECUTION_COMPLETED,
        group_id="result-processor",
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "result-processor",
            with_idempotency(body, processor.handle_execution_completed, idem, KeyStrategy.CONTENT_HASH, 7200, logger))

    @broker.subscriber(
        EventType.EXECUTION_FAILED,
        group_id="result-processor",
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "result-processor",
            with_idempotency(body, processor.handle_execution_failed, idem, KeyStrategy.CONTENT_HASH, 7200, logger))

    @broker.subscriber(
        EventType.EXECUTION_TIMEOUT,
        group_id="result-processor",
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "result-processor",
            with_idempotency(body, processor.handle_execution_timeout, idem, KeyStrategy.CONTENT_HASH, 7200, logger))


def register_saga_subscriber(broker: KafkaBroker) -> None:
    @broker.subscriber(
        EventType.EXECUTION_REQUESTED,
        group_id="saga-orchestrator",
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        coro = with_idempotency(
            body, orchestrator.handle_execution_requested, idem, KeyStrategy.EVENT_BASED, 3600, logger,
        )
        await _track_consumed(event_metrics, body, "saga-orchestrator", coro)

    @broker.subscriber(
        EventType.EXECUTION_COMPLETED,
        group_id="saga-orchestrator",
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "saga-orchestrator",
            orchestrator.handle_execution_completed(body))

    @broker.subscriber(
        EventType.EXECUTION_FAILED,
        group_id="saga-orchestrator",
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "saga-orchestrator",
            orchestrator.handle_execution_failed(body))

    @broker.subscriber(
        EventType.EXECUTION_TIMEOUT,
        group_id="saga-orchestrator",
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            orchestrator: FromDishka[SagaOrchestrator],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "saga-orchestrator",
            orchestrator.handle_execution_timeout(body))

    @broker.subscriber(
        EventType.EXECUTION_CANCELLED,
        group_id="saga-orchestrator",
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_cancelled(
            body: ExecutionCancelledEvent,
            orchestrator: FromDishka[SagaOrchestrator],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, "saga-orchestrator",
            orchestrator.handle_execution_cancelled(body))


_SSE_EVENT_TYPES = [
    EventType.EXECUTION_REQUESTED,
    EventType.EXECUTION_QUEUED,
    EventType.EXECUTION_STARTED,
    EventType.EXECUTION_RUNNING,
    EventType.EXECUTION_COMPLETED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_TIMEOUT,
    EventType.EXECUTION_CANCELLED,
    EventType.RESULT_STORED,
    EventType.RESULT_FAILED,
    EventType.POD_CREATED,
    EventType.POD_SCHEDULED,
    EventType.POD_RUNNING,
    EventType.POD_SUCCEEDED,
    EventType.POD_FAILED,
    EventType.POD_TERMINATED,
    EventType.POD_DELETED,
]


def register_sse_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    group_id = "sse-bridge-pool"

    @broker.subscriber(
        *_SSE_EVENT_TYPES,
        group_id=group_id,
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_sse_event(
            body: DomainEvent,
            sse_bus: FromDishka[SSERedisBus],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        event_metrics.record_kafka_message_consumed(topic=body.event_type, consumer_group=group_id)
        execution_id = getattr(body, "execution_id", None)
        if execution_id:
            sse_data = SSEExecutionEventData(**{
                k: v for k, v in body.model_dump().items() if k in _sse_field_names
            })
            await sse_bus.publish_event(execution_id, sse_data)


def register_notification_subscriber(broker: KafkaBroker) -> None:
    group_id = "notification-service"

    @broker.subscriber(
        EventType.EXECUTION_COMPLETED,
        group_id=group_id,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            service: FromDishka[NotificationService],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, group_id,
            service.handle_execution_completed(body))

    @broker.subscriber(
        EventType.EXECUTION_FAILED,
        group_id=group_id,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            service: FromDishka[NotificationService],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, group_id,
            service.handle_execution_failed(body))

    @broker.subscriber(
        EventType.EXECUTION_TIMEOUT,
        group_id=group_id,
        ack_policy=AckPolicy.ACK,
        max_poll_records=10,
        auto_offset_reset="latest",
    )
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            service: FromDishka[NotificationService],
            event_metrics: FromDishka[EventMetrics],
    ) -> None:
        await _track_consumed(event_metrics, body, group_id,
            service.handle_execution_timeout(body))


