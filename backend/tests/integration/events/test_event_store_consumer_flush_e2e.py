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
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


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
            ev = ExecutionRequestedEvent(
                execution_id=x,
                script="print('x')",
                language="python",
                language_version="3.11",
                runtime_image="python:3.11-slim",
                runtime_command=["python", "-c"],
                runtime_filename="main.py",
                timeout_seconds=5,
                cpu_limit="100m",
                memory_limit="128Mi",
                cpu_request="50m",
                memory_request="64Mi",
                metadata=EventMetadata(service_name="tests", service_version="1.0"),
            )
            await consumer._handle_event(ev)  # noqa: SLF001

        # Wait for batch_processor to tick (it sleeps ~1s per loop) and flush by timeout
        deadline = asyncio.get_event_loop().time() + 5.0
        have: set[str] = set()
        while asyncio.get_event_loop().time() < deadline:
            docs = await db[store.collection_name].find({"event_type": str(EventType.EXECUTION_REQUESTED)}).to_list(50)
            have = {d.get("execution_id") for d in docs}
            if set(exec_ids).issubset(have):
                break
            await asyncio.sleep(0.3)
        assert set(exec_ids).issubset(have)
    finally:
        await consumer.stop()
