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

    # Produce 2 identical events BEFORE starting consumer
    execution_id = unique_id("e-")

    # Track processed events AND duplicates separately (filter by our execution_id)
    counts = {"processed": 0, "duplicates": 0}

    async def handle(ev: Any) -> None:
        if getattr(ev, "execution_id", None) == execution_id:
            counts["processed"] += 1

    async def on_duplicate(ev: Any, _result: Any) -> None:
        if getattr(ev, "execution_id", None) == execution_id:
            counts["duplicates"] += 1

    # Build dispatcher (no auto-registration - we'll use subscribe_idempotent_handler)
    disp: Disp = EventDispatcher(logger=_test_logger)

    # Real consumer with idempotent wrapper (disable auto-wrapping)
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
        enable_for_all_handlers=False,  # Don't auto-wrap; we register with on_duplicate
        logger=_test_logger,
    )

    # Register handler WITH on_duplicate callback to track duplicates
    wrapper.subscribe_idempotent_handler(
        event_type=EventType.EXECUTION_REQUESTED,
        handler=handle,
        on_duplicate=on_duplicate,
    )

    ev = make_execution_requested_event(execution_id=execution_id)
    await producer.produce(ev, key=execution_id)
    await producer.produce(ev, key=execution_id)
    # Flush to ensure both messages are delivered to Kafka
    producer._producer.flush(timeout=5.0)  # type: ignore[union-attr]

    await wrapper.start([KafkaTopic.EXECUTION_EVENTS])
    try:
        # Wait until BOTH events have been handled (processed OR detected as duplicate)
        # Kafka consumers can be slow to start and poll - allow more time
        @backoff.on_exception(backoff.constant, AssertionError, max_time=30.0, interval=0.3)
        async def _wait_all_handled() -> None:
            total = counts["processed"] + counts["duplicates"]
            assert total >= 2, f"Expected 2 events handled, got {total}"

        await _wait_all_handled()

        # Verify exactly 1 processed, 1 duplicate blocked
        assert counts["processed"] == 1, f"Expected 1 processed, got {counts['processed']}"
        assert counts["duplicates"] == 1, f"Expected 1 duplicate blocked, got {counts['duplicates']}"
    finally:
        await wrapper.stop()
