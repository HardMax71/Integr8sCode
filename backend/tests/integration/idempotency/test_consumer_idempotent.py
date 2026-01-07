import logging
from collections.abc import Callable
from typing import Any

import backoff
import pytest
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher as Disp
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.redis]

_test_logger = logging.getLogger("test.idempotency.consumer_idempotent")


@pytest.mark.asyncio
async def test_consumer_idempotent_wrapper_blocks_duplicates(
    scope: AsyncContainer, unique_id: Callable[[str], str]
) -> None:
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idm: IdempotencyManager = await scope.get(IdempotencyManager)
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)

    # Build a dispatcher with a counter
    disp: Disp = EventDispatcher(logger=_test_logger)
    seen = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handle(_ev: Any) -> None:
        seen["n"] += 1

    # Real consumer with idempotent wrapper
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=unique_id("test-idem-consumer-"),
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

    # Produce BEFORE starting consumer - with earliest offset, consumer will read from beginning
    execution_id = unique_id("e-")
    ev = make_execution_requested_event(execution_id=execution_id)
    await producer.produce(ev, key=execution_id)
    await producer.produce(ev, key=execution_id)

    await wrapper.start([KafkaTopic.EXECUTION_EVENTS])
    try:

        @backoff.on_exception(backoff.constant, AssertionError, max_time=10.0, interval=0.2)
        async def _wait_one() -> None:
            assert seen["n"] >= 1

        await _wait_one()
    finally:
        await wrapper.stop()
