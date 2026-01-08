import asyncio
import logging
from collections.abc import Callable
from typing import Any

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

    execution_id = unique_id("e-")
    done = asyncio.Event()
    processed: list[str] = []
    duplicates: list[str] = []

    async def handle(ev: Any) -> None:
        if ev.execution_id != execution_id:
            return
        processed.append(ev.execution_id)
        if len(processed) + len(duplicates) >= 2:
            done.set()

    async def on_duplicate(ev: Any, _result: Any) -> None:
        if ev.execution_id != execution_id:
            return
        duplicates.append(ev.execution_id)
        if len(processed) + len(duplicates) >= 2:
            done.set()

    disp: Disp = EventDispatcher(logger=_test_logger)
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=unique_id("test-idem-consumer-"),
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    base = UnifiedConsumer(cfg, disp, registry, settings, _test_logger)
    wrapper = IdempotentConsumerWrapper(
        consumer=base,
        idempotency_manager=idm,
        dispatcher=disp,
        logger=_test_logger,
        default_key_strategy="event_based",
        enable_for_all_handlers=False,
    )
    wrapper.subscribe_idempotent_handler(EventType.EXECUTION_REQUESTED, handle, on_duplicate=on_duplicate)

    await wrapper.start([KafkaTopic.EXECUTION_EVENTS])

    # Wait for partition assignment
    for _ in range(100):
        if base._consumer and base._consumer.assignment():  # noqa: SLF001
            break
        await asyncio.sleep(0.1)

    # Produce after consumer is ready
    ev = make_execution_requested_event(execution_id=execution_id)
    await producer.produce(ev, key=execution_id)
    await producer.produce(ev, key=execution_id)
    if producer.producer:
        producer.producer.flush(timeout=5.0)

    await asyncio.wait_for(done.wait(), timeout=30.0)
    await wrapper.stop()

    assert processed.count(execution_id) == 1
    assert duplicates.count(execution_id) == 1
