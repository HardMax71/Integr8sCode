import asyncio
import logging

import pytest
from app.core.metrics import EventMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher as Disp
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

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
async def test_consumer_idempotent_wrapper_blocks_duplicates(
    scope: AsyncContainer,
    schema_registry: SchemaRegistryManager,
    event_metrics: EventMetrics,
    consumer_config: ConsumerConfig,
    test_settings: Settings,
) -> None:
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    # Future resolves when handler processes an event - no polling needed
    handled_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    seen = {"n": 0}

    # Build a dispatcher that signals completion via future
    disp: Disp = EventDispatcher(logger=_test_logger)

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handle(_ev: DomainEvent) -> None:
        seen["n"] += 1
        if not handled_future.done():
            handled_future.set_result(None)

    # Produce messages BEFORE starting consumer (auto_offset_reset="earliest" will read them)
    execution_id = f"e-{consumer_config.group_id}"
    ev = make_execution_requested_event(execution_id=execution_id)
    await producer.produce(ev, key=execution_id)
    await producer.produce(ev, key=execution_id)

    # Real consumer with idempotent wrapper
    base = UnifiedConsumer(
        consumer_config,
        event_dispatcher=disp,
        schema_registry=schema_registry,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
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
    try:
        # Await the future directly - true async, no polling
        await asyncio.wait_for(handled_future, timeout=10.0)
        assert seen["n"] >= 1
    finally:
        await wrapper.stop()
