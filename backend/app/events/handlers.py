import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog
from dishka.integrations.faststream import FromDishka
from faststream import AckPolicy
from faststream.kafka import KafkaBroker, KafkaMessage
from faststream.message import decode_message

from app.dlq.manager import DLQManager
from app.dlq.models import DLQMessage
from app.domain.enums import EventType, GroupId, KafkaTopic
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
from app.infrastructure.kafka.mappings import CONSUMER_GROUP_SUBSCRIPTIONS
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


def _topics(settings: Settings, group_id: GroupId) -> list[str]:
    return [
        f"{settings.KAFKA_TOPIC_PREFIX}{t}"
        for t in CONSUMER_GROUP_SUBSCRIPTIONS[group_id]
    ]


def _event_type_filter(msg: Any, expected: str) -> bool:
    """Body-based event_type filter for @sub(filter=...) lambdas."""
    return decode_message(msg).get("event_type") == expected  # type: ignore[union-attr]


def register_coordinator_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.EXECUTION_COORDINATOR),
        group_id=GroupId.EXECUTION_COORDINATOR,
        ack_policy=AckPolicy.ACK,
    )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_REQUESTED))
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_requested, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_completed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_failed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_CANCELLED))
    async def on_execution_cancelled(
            body: ExecutionCancelledEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
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

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.CREATE_POD_COMMAND))
    async def on_create_pod(
            body: CreatePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, worker.handle_create_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger,
        )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.DELETE_POD_COMMAND))
    async def on_delete_pod(
            body: DeletePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, worker.handle_delete_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger,
        )

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

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, processor.handle_execution_completed, idem, KeyStrategy.CONTENT_HASH, 7200, logger,
        )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, processor.handle_execution_failed, idem, KeyStrategy.CONTENT_HASH, 7200, logger,
        )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_TIMEOUT))
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        await with_idempotency(
            body, processor.handle_execution_timeout, idem, KeyStrategy.CONTENT_HASH, 7200, logger,
        )

    @sub
    async def on_unhandled(body: DomainEvent) -> None:
        pass


def register_saga_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.SAGA_ORCHESTRATOR),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.ACK,
    )

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_REQUESTED))
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_requested(body)

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_completed(body)

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_failed(body)

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_TIMEOUT))
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

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_completed(body)

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_failed(body)

    @sub(filter=lambda msg: _event_type_filter(msg, EventType.EXECUTION_TIMEOUT))
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

    DLQ messages are JSON-encoded DLQMessage models (Pydantic serialization via FastStream).
    All DLQ metadata is in the message body — no Kafka headers needed.
    """
    topic_name = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DEAD_LETTER_QUEUE}"

    @broker.subscriber(
        topic_name,
        group_id=GroupId.DLQ_MANAGER,
        ack_policy=AckPolicy.ACK,
        auto_offset_reset="earliest",
    )
    async def on_dlq_message(
            body: DLQMessage,
            msg: KafkaMessage,
            manager: FromDishka[DLQManager],
            logger: FromDishka[structlog.stdlib.BoundLogger],
    ) -> None:
        start = asyncio.get_running_loop().time()
        raw = msg.raw_message
        assert not isinstance(raw, tuple)
        body.dlq_offset = raw.offset
        body.dlq_partition = raw.partition

        await manager.handle_message(body)

        manager.metrics.record_dlq_message_received(body.original_topic, body.event.event_type)
        manager.metrics.record_dlq_message_age(
            (datetime.now(timezone.utc) - body.failed_at).total_seconds()
        )
        manager.metrics.record_dlq_processing_duration(
            asyncio.get_running_loop().time() - start, "process"
        )
