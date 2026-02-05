import logging

import pytest

from app.domain.events.typed import DomainEventAdapter
from app.events.schema.schema_registry import SchemaRegistryManager
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e]

_test_logger = logging.getLogger("test.events.schema_registry_roundtrip")


@pytest.mark.asyncio
async def test_schema_registry_serialize_deserialize_roundtrip(scope: AsyncContainer) -> None:
    reg: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    ev = make_execution_requested_event(execution_id="e-rt")
    data = await reg.serialize_event(ev)
    assert data[:1] == b"\x00"  # Confluent wire format magic byte
    payload = await reg.serializer.decode_message(data)
    assert payload is not None
    back = DomainEventAdapter.validate_python(payload)
    assert back.event_id == ev.event_id and getattr(back, "execution_id", None) == ev.execution_id
