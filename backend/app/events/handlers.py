import dataclasses

from dishka_faststream import FromDishka
from faststream import AckPolicy
from faststream.kafka import KafkaRouter

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
    PodRunningEvent,
    PodScheduledEvent,
)
from app.domain.idempotency import KeyStrategy
from app.domain.sse import SSEExecutionEventData
from app.events.middlewares import DeadLetterMiddleware, idempotent
from app.infrastructure.kafka.topics import POD_EVENT_STATUS
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_service import NotificationService
from app.services.result_processor import ResultProcessor
from app.services.saga import SagaOrchestrator
from app.services.sse import SSERedisBus
from app.settings import Settings

_sse_field_names: frozenset[str] = frozenset(f.name for f in dataclasses.fields(SSEExecutionEventData))


def k8s_worker_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.CONTENT_HASH, ttl_seconds=3600)),
    )

    @router.subscriber(EventType.CREATE_POD_COMMAND, group_id="k8s-worker")
    async def on_create_pod(body: CreatePodCommandEvent, worker: FromDishka[KubernetesWorker]) -> None:
        await worker.handle_create_pod_command(body)

    @router.subscriber(EventType.DELETE_POD_COMMAND, group_id="k8s-worker")
    async def on_delete_pod(body: DeletePodCommandEvent, worker: FromDishka[KubernetesWorker]) -> None:
        await worker.handle_delete_pod_command(body)

    return router


def result_processor_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.CONTENT_HASH, ttl_seconds=7200)),
    )

    @router.subscriber(
        EventType.EXECUTION_COMPLETED, group_id="result-processor", max_poll_records=1, auto_offset_reset="earliest"
    )
    async def on_execution_completed(body: ExecutionCompletedEvent, processor: FromDishka[ResultProcessor]) -> None:
        await processor.handle_execution_completed(body)

    @router.subscriber(
        EventType.EXECUTION_FAILED, group_id="result-processor", max_poll_records=1, auto_offset_reset="earliest"
    )
    async def on_execution_failed(body: ExecutionFailedEvent, processor: FromDishka[ResultProcessor]) -> None:
        await processor.handle_execution_failed(body)

    @router.subscriber(
        EventType.EXECUTION_TIMEOUT, group_id="result-processor", max_poll_records=1, auto_offset_reset="earliest"
    )
    async def on_execution_timeout(body: ExecutionTimeoutEvent, processor: FromDishka[ResultProcessor]) -> None:
        await processor.handle_execution_timeout(body)

    @router.subscriber(EventType.POD_SCHEDULED, group_id="result-processor", auto_offset_reset="earliest")
    async def on_pod_scheduled(body: PodScheduledEvent, processor: FromDishka[ResultProcessor]) -> None:
        await processor.handle_pod_progress(body)

    @router.subscriber(EventType.POD_RUNNING, group_id="result-processor", auto_offset_reset="earliest")
    async def on_pod_running(body: PodRunningEvent, processor: FromDishka[ResultProcessor]) -> None:
        await processor.handle_pod_progress(body)

    return router


def saga_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.EVENT_BASED, ttl_seconds=3600)),
    )

    @router.subscriber(EventType.EXECUTION_REQUESTED, group_id="saga-orchestrator")
    async def on_execution_requested(body: ExecutionRequestedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
        await saga.handle_execution_requested(body)

    @router.subscriber(EventType.EXECUTION_COMPLETED, group_id="saga-orchestrator")
    async def on_execution_completed(body: ExecutionCompletedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
        await saga.handle_execution_completed(body)

    @router.subscriber(EventType.EXECUTION_FAILED, group_id="saga-orchestrator")
    async def on_execution_failed(body: ExecutionFailedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
        await saga.handle_execution_failed(body)

    @router.subscriber(EventType.EXECUTION_TIMEOUT, group_id="saga-orchestrator")
    async def on_execution_timeout(body: ExecutionTimeoutEvent, saga: FromDishka[SagaOrchestrator]) -> None:
        await saga.handle_execution_timeout(body)

    @router.subscriber(EventType.EXECUTION_CANCELLED, group_id="saga-orchestrator")
    async def on_execution_cancelled(body: ExecutionCancelledEvent, saga: FromDishka[SagaOrchestrator]) -> None:
        await saga.handle_execution_cancelled(body)

    return router


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


def sse_router(settings: Settings) -> KafkaRouter:
    router = KafkaRouter(ack_policy=AckPolicy.ACK_FIRST)

    @router.subscriber(
        *_SSE_EVENT_TYPES,
        group_id="sse-bridge-pool",
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_sse_event(body: DomainEvent, sse_bus: FromDishka[SSERedisBus]) -> None:
        execution_id = getattr(body, "execution_id", None)
        if execution_id:
            fields = {k: v for k, v in body.model_dump().items() if k in _sse_field_names}
            fields.setdefault("status", POD_EVENT_STATUS.get(body.event_type))
            await sse_bus.publish_event(execution_id, SSEExecutionEventData(**fields))

    return router


def notification_router() -> KafkaRouter:
    router = KafkaRouter(ack_policy=AckPolicy.ACK, middlewares=(DeadLetterMiddleware,))

    @router.subscriber(
        EventType.EXECUTION_COMPLETED, group_id="notification-service", max_poll_records=10, auto_offset_reset="latest"
    )
    async def on_execution_completed(body: ExecutionCompletedEvent, service: FromDishka[NotificationService]) -> None:
        await service.handle_execution_completed(body)

    @router.subscriber(
        EventType.EXECUTION_FAILED, group_id="notification-service", max_poll_records=10, auto_offset_reset="latest"
    )
    async def on_execution_failed(body: ExecutionFailedEvent, service: FromDishka[NotificationService]) -> None:
        await service.handle_execution_failed(body)

    @router.subscriber(
        EventType.EXECUTION_TIMEOUT, group_id="notification-service", max_poll_records=10, auto_offset_reset="latest"
    )
    async def on_execution_timeout(body: ExecutionTimeoutEvent, service: FromDishka[NotificationService]) -> None:
        await service.handle_execution_timeout(body)

    return router
