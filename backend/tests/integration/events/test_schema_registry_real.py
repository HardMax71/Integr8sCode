import pytest
from app.domain.events.typed import EventMetadata, PodCreatedEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.mappings import get_topic_for_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka]


@pytest.mark.asyncio
async def test_serialize_and_deserialize_event_real_registry(
    schema_registry: SchemaRegistryManager,
) -> None:
    # Uses real Schema Registry configured via env (SCHEMA_REGISTRY_URL)
    ev = PodCreatedEvent(
        execution_id="e1",
        pod_name="p",
        namespace="n",
        metadata=EventMetadata(service_name="s", service_version="1"),
    )
    data = await schema_registry.serialize_event(ev)
    topic = str(get_topic_for_event(ev.event_type))
    obj = await schema_registry.deserialize_event(data, topic=topic)
    assert isinstance(obj, PodCreatedEvent)
    assert obj.namespace == "n"
