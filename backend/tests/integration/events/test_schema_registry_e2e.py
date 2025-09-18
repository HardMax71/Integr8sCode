import asyncio
import struct

import pytest

from app.events.schema.schema_registry import SchemaRegistryManager, MAGIC_BYTE
from tests.helpers import make_execution_requested_event


pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_schema_registry_serialize_deserialize_roundtrip(scope):  # type: ignore[valid-type]
    reg: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    # Schema registration happens lazily in serialize_event
    ev = make_execution_requested_event(execution_id="e-rt")
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
