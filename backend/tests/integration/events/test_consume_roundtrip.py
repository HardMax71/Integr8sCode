import asyncio
import uuid

import pytest

from app.domain.enums.events import EventType
from app.events.core import UnifiedConsumer, UnifiedProducer
from app.events.core.types import ConsumerConfig
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.domain.enums.kafka import KafkaTopic
from tests.helpers import make_execution_requested_event
from app.core.metrics.context import get_event_metrics
from app.events.core.dispatcher import EventDispatcher
from app.settings import get_settings


pytestmark = [pytest.mark.integration, pytest.mark.kafka]


@pytest.mark.asyncio
async def test_produce_consume_roundtrip(scope) -> None:  # type: ignore[valid-type]
    # Ensure schemas are registered
    registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    await initialize_event_schemas(registry)

    # Real producer from DI
    producer: UnifiedProducer = await scope.get(UnifiedProducer)

    # Build a consumer that handles EXECUTION_REQUESTED
    settings = get_settings()
    dispatcher = EventDispatcher()
    received = asyncio.Event()

    @dispatcher.register(EventType.EXECUTION_REQUESTED)
    async def _handle(_event) -> None:  # noqa: ANN001
        received.set()

    group_id = f"test-consumer.{uuid.uuid4().hex[:6]}"
    config = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )

    consumer = UnifiedConsumer(config, dispatcher)
    await consumer.start([str(KafkaTopic.EXECUTION_EVENTS)])

    try:
        # Produce a request event
        execution_id = f"exec-{uuid.uuid4().hex[:8]}"
        evt = make_execution_requested_event(execution_id=execution_id)
        await producer.produce(evt, key=execution_id)

        # Wait for the handler to be called
        await asyncio.wait_for(received.wait(), timeout=10.0)
    finally:
        await consumer.stop()
