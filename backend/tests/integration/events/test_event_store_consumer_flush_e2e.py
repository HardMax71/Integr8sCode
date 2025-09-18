import asyncio
from uuid import uuid4

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.event_store import EventStore
from app.events.event_store_consumer import create_event_store_consumer
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_event_store_consumer_flush_on_timeout(scope):  # type: ignore[valid-type]
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    db: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)
    store = EventStore(db=db, schema_registry=schema)
    await store.initialize()

    consumer = create_event_store_consumer(
        event_store=store,
        topics=[KafkaTopic.EXECUTION_EVENTS],
        schema_registry_manager=schema,
        producer=producer,
        batch_size=100,
        batch_timeout_seconds=0.2,
    )
    await consumer.start()
    try:
        # Directly invoke handler to enqueue
        exec_ids = []
        for _ in range(3):
            x = f"exec-{uuid4().hex[:6]}"
            exec_ids.append(x)
            ev = make_execution_requested_event(execution_id=x)
            await consumer._handle_event(ev)  # noqa: SLF001

        async def _all_present() -> None:
            docs = await db[store.collection_name].find({"event_type": str(EventType.EXECUTION_REQUESTED)}).to_list(50)
            have = {d.get("execution_id") for d in docs}
            assert set(exec_ids).issubset(have)

        await eventually(_all_present, timeout=5.0, interval=0.2)
    finally:
        await consumer.stop()
