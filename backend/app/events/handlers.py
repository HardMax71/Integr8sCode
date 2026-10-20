import dataclasses

from dishka_faststream import FromDishka
from faststream import AckPolicy
from faststream.kafka import KafkaRouter

from app.domain.enums import EventType
from app.domain.events import (
    DomainEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    ExecutionTimeoutEvent,
)
from app.domain.idempotency import KeyStrategy
from app.domain.sse import SSEExecutionEventData
from app.events.middlewares import DeadLetterMiddleware, idempotent
from app.infrastructure.kafka.topics import POD_EVENT_STATUS
from app.services.execution_scheduler import ExecutionScheduler
from app.services.notification_service import NotificationService
from app.services.sse import SSERedisBus
from app.settings import Settings

_sse_field_names: frozenset[str] = frozenset(f.name for f in dataclasses.fields(SSEExecutionEventData))


async def schedule_execution(body: ExecutionRequestedEvent, scheduler: FromDishka[ExecutionScheduler]) -> None:
    await scheduler.handle_execution_requested(body)


async def cancel_execution(body: ExecutionCancelledEvent, scheduler: FromDishka[ExecutionScheduler]) -> None:
    await scheduler.handle_execution_cancelled(body)


def scheduler_router() -> KafkaRouter:
    router = KafkaRouter(
        ack_policy=AckPolicy.ACK,
        middlewares=(DeadLetterMiddleware, idempotent(KeyStrategy.EVENT_BASED, ttl_seconds=3600)),
    )
    # The saga orchestrator's group id, so the offsets it committed carry over and a deploy skips no request
    router.subscriber(EventType.EXECUTION_REQUESTED, group_id="saga-orchestrator")(schedule_execution)
    router.subscriber(EventType.EXECUTION_CANCELLED, group_id="saga-orchestrator")(cancel_execution)
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
