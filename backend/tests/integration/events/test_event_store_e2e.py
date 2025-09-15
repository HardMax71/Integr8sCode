from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.domain.enums.events import EventType
from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_event_store_initialize_and_crud(scope):  # type: ignore[valid-type]
    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    db: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)
    store = EventStore(db=db, schema_registry=schema, ttl_days=1)
    await store.initialize()

    # Store single event
    ev = ExecutionRequestedEvent(
        execution_id="e-1",
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
    assert await store.store_event(ev) is True

    # Duplicate insert should be treated as success True (DuplicateKey swallowed)
    assert await store.store_event(ev) is True

    # Batch store with duplicates
    ev2 = ev.model_copy(update={"event_id": "new-2", "execution_id": "e-2"})
    res = await store.store_batch([ev, ev2])
    assert res["total"] == 2 and res["stored"] >= 1

    # Queries
    by_id = await store.get_event(ev.event_id)
    assert by_id is not None and by_id.event_id == ev.event_id

    by_type = await store.get_events_by_type(EventType.EXECUTION_REQUESTED, limit=10)
    assert any(e.event_id == ev.event_id for e in by_type)

    by_exec = await store.get_execution_events("e-1")
    assert any(e.event_id == ev.event_id for e in by_exec)

    by_user = await store.get_user_events("u-unknown", limit=10)
    assert isinstance(by_user, list)

