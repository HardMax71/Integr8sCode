import logging
from collections.abc import Awaitable, Callable
from typing import Any

from dishka.integrations.faststream import FromDishka
from faststream import AckPolicy, StreamMessage
from faststream.kafka import KafkaBroker

from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
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
from app.events.core import UnifiedProducer
from app.events.event_store import EventStore
from app.infrastructure.kafka.mappings import EVENT_TYPE_TO_TOPIC
from app.infrastructure.kafka.topics import get_all_topics
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.services.idempotency import IdempotencyManager
from app.services.k8s_worker import KubernetesWorker
from app.services.notification_service import NotificationService
from app.services.result_processor.processor import ResultProcessor
from app.services.saga import SagaOrchestrator
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings


def for_event(
        *event_types: EventType,
) -> Callable[[StreamMessage[Any]], bool]:
    """Sync filter: match messages whose ``event_type`` header is in *event_types*.

    The producer writes ``event_type`` into Kafka headers as a plain string,
    and FastStream exposes headers as ``dict[str, str]``.  Because
    ``EventType(StringEnum)`` compares equal to its string value the
    ``in`` check works without any conversion.
    """
    accepted = frozenset(event_types)

    def _filter(msg: StreamMessage[Any]) -> bool:
        return msg.headers.get("event_type", "") in accepted

    return _filter


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
        ack_policy=AckPolicy.REJECT_ON_ERROR,
    )

    @sub(filter=for_event(EventType.EXECUTION_REQUESTED))
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_requested, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=for_event(EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_completed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=for_event(EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            coordinator: FromDishka[ExecutionCoordinator],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(
            body, coordinator.handle_execution_failed, idem, KeyStrategy.EVENT_BASED, 7200, logger,
        )

    @sub(filter=for_event(EventType.EXECUTION_CANCELLED))
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
    sub = broker.subscriber(
        *_topics(settings, GroupId.K8S_WORKER),
        group_id=GroupId.K8S_WORKER,
        ack_policy=AckPolicy.REJECT_ON_ERROR,
    )

    @sub(filter=for_event(EventType.CREATE_POD_COMMAND))
    async def on_create_pod(
            body: CreatePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, worker.handle_create_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger)

    @sub(filter=for_event(EventType.DELETE_POD_COMMAND))
    async def on_delete_pod(
            body: DeletePodCommandEvent,
            worker: FromDishka[KubernetesWorker],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, worker.handle_delete_pod_command, idem, KeyStrategy.CONTENT_HASH, 3600, logger)


def register_result_processor_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.RESULT_PROCESSOR),
        group_id=GroupId.RESULT_PROCESSOR,
        ack_policy=AckPolicy.REJECT_ON_ERROR,
        max_poll_records=1,
        auto_offset_reset="earliest",
    )

    @sub(filter=for_event(EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, processor.handle_execution_completed, idem, KeyStrategy.CONTENT_HASH, 7200, logger)

    @sub(filter=for_event(EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, processor.handle_execution_failed, idem, KeyStrategy.CONTENT_HASH, 7200, logger)

    @sub(filter=for_event(EventType.EXECUTION_TIMEOUT))
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            processor: FromDishka[ResultProcessor],
            idem: FromDishka[IdempotencyManager],
            logger: FromDishka[logging.Logger],
    ) -> None:
        await with_idempotency(body, processor.handle_execution_timeout, idem, KeyStrategy.CONTENT_HASH, 7200, logger)


def register_saga_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    sub = broker.subscriber(
        *_topics(settings, GroupId.SAGA_ORCHESTRATOR),
        group_id=GroupId.SAGA_ORCHESTRATOR,
        ack_policy=AckPolicy.REJECT_ON_ERROR,
    )

    @sub(filter=for_event(EventType.EXECUTION_REQUESTED))
    async def on_execution_requested(
            body: ExecutionRequestedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_requested(body)

    @sub(filter=for_event(EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_completed(body)

    @sub(filter=for_event(EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_failed(body)

    @sub(filter=for_event(EventType.EXECUTION_TIMEOUT))
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            orchestrator: FromDishka[SagaOrchestrator],
    ) -> None:
        await orchestrator.handle_execution_timeout(body)


def register_event_store_subscriber(broker: KafkaBroker, settings: Settings) -> None:
    topics = [f"{settings.KAFKA_TOPIC_PREFIX}{t}" for t in get_all_topics()]

    @broker.subscriber(
        *topics,
        group_id="event-store-consumer",
        ack_policy=AckPolicy.REJECT_ON_ERROR,
        max_poll_records=100,
    )
    async def on_any_event(
            body: DomainEvent,
            event_store: FromDishka[EventStore],
            producer: FromDishka[UnifiedProducer],
            logger: FromDishka[logging.Logger],
    ) -> None:
        try:
            await event_store.store_event(body)
        except Exception as err:
            logger.error(f"Error storing event {body.event_id}: {err}", exc_info=True)
            topic = str(EVENT_TYPE_TO_TOPIC.get(body.event_type, "unknown"))
            await producer.send_to_dlq(body, topic, err, 0)


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
        ack_policy=AckPolicy.REJECT_ON_ERROR,
        max_poll_records=10,
        auto_offset_reset="latest",
    )

    @sub(filter=for_event(EventType.EXECUTION_COMPLETED))
    async def on_execution_completed(
            body: ExecutionCompletedEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_completed(body)

    @sub(filter=for_event(EventType.EXECUTION_FAILED))
    async def on_execution_failed(
            body: ExecutionFailedEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_failed(body)

    @sub(filter=for_event(EventType.EXECUTION_TIMEOUT))
    async def on_execution_timeout(
            body: ExecutionTimeoutEvent,
            service: FromDishka[NotificationService],
    ) -> None:
        await service.handle_execution_timeout(body)
