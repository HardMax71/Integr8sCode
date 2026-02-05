import logging

import pytest

from app.domain.events.typed import DomainEventAdapter, EventMetadata, PodCreatedEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.schema_registry_real")


@pytest.mark.asyncio
async def test_serialize_and_deserialize_event_real_registry(test_settings: Settings) -> None:
    # Uses real Schema Registry configured via env (SCHEMA_REGISTRY_URL)
    m = SchemaRegistryManager(settings=test_settings, logger=_test_logger)
    ev = PodCreatedEvent(
        execution_id="e1",
        pod_name="p",
        namespace="n",
        metadata=EventMetadata(service_name="s", service_version="1"),
    )
    data = await m.serialize_event(ev)
    payload = await m.serializer.decode_message(data)
    assert payload is not None
    obj = DomainEventAdapter.validate_python(payload)
    assert isinstance(obj, PodCreatedEvent)
    assert obj.namespace == "n"
