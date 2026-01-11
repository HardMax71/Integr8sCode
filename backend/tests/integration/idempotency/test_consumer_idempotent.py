import asyncio
import logging
import uuid

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher as Disp
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

# xdist_group: Kafka consumer creation can crash librdkafka when multiple workers
# instantiate Consumer() objects simultaneously. Serial execution prevents this.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.kafka,
    pytest.mark.redis,
    pytest.mark.xdist_group("kafka_consumers"),
]

_test_logger = logging.getLogger("test.idempotency.consumer_idempotent")


@pytest.mark.asyncio
async def test_consumer_idempotent_wrapper_blocks_duplicates(scope: AsyncContainer) -> None:
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idm: IdempotencyManager = await scope.get(IdempotencyManager)
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)

    # Build a dispatcher with a counter
    disp: Disp = EventDispatcher(logger=_test_logger)
    seen = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handle(_ev: BaseEvent) -> None:
        seen["n"] += 1

    # Real consumer with idempotent wrapper
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-idem-consumer.{uuid.uuid4().hex[:6]}",
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    base = UnifiedConsumer(
        cfg,
        event_dispatcher=disp,
        schema_registry=registry,
        settings=settings,
        logger=_test_logger,
    )
    wrapper = IdempotentConsumerWrapper(
        consumer=base,
        idempotency_manager=idm,
        dispatcher=disp,
        default_key_strategy="event_based",
        enable_for_all_handlers=True,
        logger=_test_logger,
    )

    await wrapper.start([KafkaTopic.EXECUTION_EVENTS])
    # Allow time for consumer to join group and get partition assignments
    await asyncio.sleep(2)
    try:
        # Produce the same event twice (same event_id)
        execution_id = f"e-{uuid.uuid4().hex[:8]}"
        ev = make_execution_requested_event(execution_id=execution_id)
        await producer.produce(ev, key=execution_id)
        await producer.produce(ev, key=execution_id)

        async def _one() -> None:
            assert seen["n"] >= 1

        await eventually(_one, timeout=10.0, interval=0.2)
    finally:
        await wrapper.stop()
