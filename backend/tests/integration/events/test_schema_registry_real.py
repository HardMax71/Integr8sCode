import pytest

from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.events.pod import PodCreatedEvent

pytestmark = [pytest.mark.integration, pytest.mark.kafka]


def test_serialize_and_deserialize_event_real_registry() -> None:
    # Uses real Schema Registry configured via env (SCHEMA_REGISTRY_URL)
    m = SchemaRegistryManager()
    ev = PodCreatedEvent(
        execution_id="e1",
        pod_name="p",
        namespace="n",
        metadata=EventMetadata(service_name="s", service_version="1"),
    )
    data = m.serialize_event(ev)
    obj = m.deserialize_event(data, topic=str(ev.topic))
    assert isinstance(obj, PodCreatedEvent)
    assert obj.namespace == "n"
