import asyncio
import logging
import uuid

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.event_dispatcher")


@pytest.mark.asyncio
async def test_dispatcher_with_multiple_handlers(scope) -> None:  # type: ignore[valid-type]
    # Ensure schema registry is ready
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    settings: Settings = await scope.get(Settings)
    await initialize_event_schemas(registry)

    # Build dispatcher with two handlers for the same event
    dispatcher = EventDispatcher(logger=_test_logger)
    h1_called = asyncio.Event()
    h2_called = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def h1(_e) -> None:  # noqa: ANN001
        h1_called.set()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def h2(_e) -> None:  # noqa: ANN001
        h2_called.set()

    # Real consumer against execution-events
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"dispatcher-it.{uuid.uuid4().hex[:6]}",
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
    await consumer.start([str(KafkaTopic.EXECUTION_EVENTS)])

    # Produce a request event via DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    evt = make_execution_requested_event(execution_id=f"exec-{uuid.uuid4().hex[:8]}")
    await producer.produce(evt, key="k")

    try:
        await asyncio.wait_for(asyncio.gather(h1_called.wait(), h2_called.wait()), timeout=10.0)
    finally:
        await consumer.stop()
