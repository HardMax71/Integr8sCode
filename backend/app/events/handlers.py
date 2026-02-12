import logging
from typing import Any

from dishka.integrations.faststream import FromDishka
from faststream import AckPolicy
from faststream.kafka import KafkaBroker

from app.domain.enums import EventType, GroupId
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
from app.services.coordinator import ExecutionCoordinator
from app.services.idempotency import IdempotencyManager
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_service import NotificationService
from app.services.result_processor import ResultProcessor
from app.services.saga import SagaOrchestrator
from app.services.sse import SSERedisBus
from app.settings import Settings


async def with_idempotency(
        event: DomainEvent,
        handler: Any,
        idem: IdempotencyManager,
        key_strategy: KeyStrategy,
        ttl_seconds: int,
        logger: logging.Logger,
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


def _topic(settings: Settings, event_type: EventType) -> str:
    return f"{settings.KAFKA_TOPIC_PREFIX}{event_type}"


def register_coordinator_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_REQUESTED),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_requested, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_COMPLETED),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_completed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_FAILED),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_failed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_CANCELLED),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_cancelled(
            body: ExecutionCancelledEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_cancelled, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )


def register_k8s_worker_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    @broker.subscriber(
        _topic(settings, EventType.CREATE_POD_COMMAND),
        group_id=GroupId.K8S_WORKER,
        ack_policy=AckPolicy.ACK,
    )
    async def on_create_pod(
            body: CreatePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, worker.handle_create_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger,
        )

    @broker.subscriber(
        _topic(settings, EventType.DELETE_POD_COMMAND),
        group_id=GroupId.K8S_WORKER,
        ack_policy=AckPolicy.ACK,
    )
    async def on_delete_pod(
            body: DeletePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, worker.handle_delete_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger,
        )


def register_result_processor_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_COMPLETED),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, processor.handle_execution_completed, idem, KeyStrategy.CONTENT_HASH, 7200, logger,
        )

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_FAILED),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, processor.handle_execution_failed, idem, KeyStrategy.CONTENT_HASH, 7200, logger,
        )

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_TIMEOUT),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.ACK,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, processor.handle_execution_timeout, idem, KeyStrategy.CONTENT_HASH, 7200, logger,
        )


def register_saga_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_REQUESTED),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_requested(body)

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_COMPLETED),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_completed(body)

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_FAILED),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_failed(body)

    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_TIMEOUT),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_timeout(body)


def register_sse_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sse_topics = [_topic(settings, et) for et in SSERedisBus.SSE_ROUTED_EVENTS]

    @broker.subscriber(
        *sse_topics,
        group_id="sse-bridge-pool",
        ack_policy=AckPolicy.ACK_FIRST,
        auto_offset_reset="latest",
        max_workers=settings.SSE_CONSUMER_POOL_SIZE,
    )
    async def on_sse_event(
            body: DomainEvent,
            sse_bus: FromDishka[SSERedisBus],
    ) -> None:
        await sse_bus.route_domain_event(body)


def register_notification_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    @broker.subscriber(
        _topic(settings, EventType.EXECUTION_COMPLETED),
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
        _topic(settings, EventType.EXECUTION_FAILED),
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
        _topic(settings, EventType.EXECUTION_TIMEOUT),
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


