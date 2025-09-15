import asyncio
import struct

import pytest

from app.events.schema.schema_registry import SchemaRegistryManager, MAGIC_BYTE
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_schema_registry_serialize_deserialize_roundtrip(scope):  # type: ignore[valid-type]
    reg: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    # Schema registration happens lazily in serialize_event
    ev = ExecutionRequestedEvent(
        execution_id="e-rt",
        script="print('ok')",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python", "-c"],
        runtime_filename="main.py",
        timeout_seconds=1,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        metadata=EventMetadata(service_name="tests", service_version="1.0"),
    )
    data = reg.serialize_event(ev)
    assert data.startswith(MAGIC_BYTE)
    back = reg.deserialize_event(data, topic=str(ev.topic))
    assert back.event_id == ev.event_id and back.execution_id == ev.execution_id

    # initialize_schemas should be a no-op if already initialized; call to exercise path
    await reg.initialize_schemas()


def test_schema_registry_deserialize_invalid_header():
    reg = SchemaRegistryManager()
    with pytest.raises(ValueError):
        reg.deserialize_event(b"\x01\x00\x00\x00\x01", topic="t")  # wrong magic byte
