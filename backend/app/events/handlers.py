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


async def create_pod(body: CreatePodCommandEvent, worker: FromDishka[KubernetesWorker]) -> None:
    await worker.handle_create_pod_command(body)


async def delete_pod(body: DeletePodCommandEvent, worker: FromDishka[KubernetesWorker]) -> None:
    await worker.handle_delete_pod_command(body)


def k8s_worker_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.CONTENT_HASH, ttl_seconds=3600)),
    )
    router.subscriber(EventType.CREATE_POD_COMMAND, group_id="k8s-worker")(create_pod)
    router.subscriber(EventType.DELETE_POD_COMMAND, group_id="k8s-worker")(delete_pod)
    return router


async def store_completed_result(body: ExecutionCompletedEvent, processor: FromDishka[ResultProcessor]) -> None:
    await processor.handle_execution_completed(body)


async def store_failed_result(body: ExecutionFailedEvent, processor: FromDishka[ResultProcessor]) -> None:
    await processor.handle_execution_failed(body)


async def store_timeout_result(body: ExecutionTimeoutEvent, processor: FromDishka[ResultProcessor]) -> None:
    await processor.handle_execution_timeout(body)


async def advance_on_pod_scheduled(body: PodScheduledEvent, processor: FromDishka[ResultProcessor]) -> None:
    await processor.handle_pod_progress(body)


async def advance_on_pod_running(body: PodRunningEvent, processor: FromDishka[ResultProcessor]) -> None:
    await processor.handle_pod_progress(body)


def result_processor_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.CONTENT_HASH, ttl_seconds=7200)),
    )
    router.subscriber(
        EventType.EXECUTION_COMPLETED, group_id="result-processor", max_poll_records=1, auto_offset_reset="earliest"
    )(store_completed_result)
    router.subscriber(
        EventType.EXECUTION_FAILED, group_id="result-processor", max_poll_records=1, auto_offset_reset="earliest"
    )(store_failed_result)
    router.subscriber(
        EventType.EXECUTION_TIMEOUT, group_id="result-processor", max_poll_records=1, auto_offset_reset="earliest"
    )(store_timeout_result)
    router.subscriber(EventType.POD_SCHEDULED, group_id="result-processor", auto_offset_reset="earliest")(
        advance_on_pod_scheduled
    )
    router.subscriber(EventType.POD_RUNNING, group_id="result-processor", auto_offset_reset="earliest")(
        advance_on_pod_running
    )
    return router


async def start_saga(body: ExecutionRequestedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
    await saga.handle_execution_requested(body)


async def finish_saga_on_completed(body: ExecutionCompletedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
    await saga.handle_execution_completed(body)


async def finish_saga_on_failed(body: ExecutionFailedEvent, saga: FromDishka[SagaOrchestrator]) -> None:
    await saga.handle_execution_failed(body)


async def finish_saga_on_timeout(body: ExecutionTimeoutEvent, saga: FromDishka[SagaOrchestrator]) -> None:
    await saga.handle_execution_timeout(body)


async def finish_saga_on_cancelled(body: ExecutionCancelledEvent, saga: FromDishka[SagaOrchestrator]) -> None:
    await saga.handle_execution_cancelled(body)


def saga_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.EVENT_BASED, ttl_seconds=3600)),
    )
    router.subscriber(EventType.EXECUTION_REQUESTED, group_id="saga-orchestrator")(start_saga)
    router.subscriber(EventType.EXECUTION_COMPLETED, group_id="saga-orchestrator")(finish_saga_on_completed)
    router.subscriber(EventType.EXECUTION_FAILED, group_id="saga-orchestrator")(finish_saga_on_failed)
    router.subscriber(EventType.EXECUTION_TIMEOUT, group_id="saga-orchestrator")(finish_saga_on_timeout)
    router.subscriber(EventType.EXECUTION_CANCELLED, group_id="saga-orchestrator")(finish_saga_on_cancelled)
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


async def forward_to_sse(body: DomainEvent, sse_bus: FromDishka[SSERedisBus]) -> None:
    execution_id = getattr(body, "execution_id", None)
    if execution_id:
        fields = {k: v for k, v in body.model_dump().items() if k in _sse_field_names}
        fields.setdefault("status", POD_EVENT_STATUS.get(body.event_type))
        await sse_bus.publish_event(execution_id, SSEExecutionEventData(**fields))


def sse_router(settings: Settings) -> KafkaRouter:
    router = KafkaRouter(ack_policy=AckPolicy.ACK_FIRST)
    router.subscriber(
        *_SSE_EVENT_TYPES,
        group_id="sse-bridge-pool",
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )(forward_to_sse)
    return router


async def notify_completed(body: ExecutionCompletedEvent, service: FromDishka[NotificationService]) -> None:
    await service.handle_execution_completed(body)


async def notify_failed(body: ExecutionFailedEvent, service: FromDishka[NotificationService]) -> None:
    await service.handle_execution_failed(body)


async def notify_timeout(body: ExecutionTimeoutEvent, service: FromDishka[NotificationService]) -> None:
    await service.handle_execution_timeout(body)


def notification_router() -> KafkaRouter:
    router = KafkaRouter(ack_policy=AckPolicy.ACK, middlewares=(DeadLetterMiddleware,))
    router.subscriber(
        EventType.EXECUTION_COMPLETED, group_id="notification-service", max_poll_records=10, auto_offset_reset="latest"
    )(notify_completed)
    router.subscriber(
        EventType.EXECUTION_FAILED, group_id="notification-service", max_poll_records=10, auto_offset_reset="latest"
    )(notify_failed)
    router.subscriber(
        EventType.EXECUTION_TIMEOUT, group_id="notification-service", max_poll_records=10, auto_offset_reset="latest"
    )(notify_timeout)
    return router
