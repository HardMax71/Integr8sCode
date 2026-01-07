import asyncio
import logging
from collections.abc import Callable
from typing import Any

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.consume_roundtrip")


@pytest.mark.asyncio
async def test_produce_consume_roundtrip(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    # Ensure schemas are registered
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    await initialize_event_schemas(registry)

    # Real producer from DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)

    # Build a consumer that handles EXECUTION_REQUESTED
    dispatcher = EventDispatcher(logger=_test_logger)
    received = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def _handle(_event: Any) -> None:
        received.set()

    group_id = unique_id("test-consumer-")
    config = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )

    consumer = UnifiedConsumer(
        config,
        dispatcher,
        schema_registry=registry,
        settings=settings,
        logger=_test_logger,
    )

    # Produce BEFORE starting consumer - with earliest offset, consumer will read from beginning
    execution_id = unique_id("exec-")
    evt = make_execution_requested_event(execution_id=execution_id)
    await producer.produce(evt, key=execution_id)

    await consumer.start([KafkaTopic.EXECUTION_EVENTS])

    try:
        await asyncio.wait_for(received.wait(), timeout=10.0)
    finally:
        await consumer.stop()
