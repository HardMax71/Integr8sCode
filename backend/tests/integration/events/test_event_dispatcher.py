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

_test_logger = logging.getLogger("test.events.event_dispatcher")


@pytest.mark.asyncio
async def test_dispatcher_with_multiple_handlers(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    # Ensure schema registry is ready
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    await initialize_event_schemas(registry)

    # Build dispatcher with two handlers for the same event
    dispatcher = EventDispatcher(logger=_test_logger)
    h1_called = asyncio.Event()
    h2_called = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def h1(_e: Any) -> None:
        h1_called.set()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def h2(_e: Any) -> None:
        h2_called.set()

    # Real consumer against execution-events
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=unique_id("dispatcher-it-"),
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    consumer = UnifiedConsumer(
        cfg,
        dispatcher,
        schema_registry=registry,
        settings=settings,
        logger=_test_logger,
    )

    # Produce BEFORE starting consumer - with earliest offset, consumer will read from beginning
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    evt = make_execution_requested_event(execution_id=unique_id("exec-"))
    await producer.produce(evt, key="k")

    await consumer.start([KafkaTopic.EXECUTION_EVENTS])

    try:
        await asyncio.wait_for(asyncio.gather(h1_called.wait(), h2_called.wait()), timeout=10.0)
    finally:
        await consumer.stop()
