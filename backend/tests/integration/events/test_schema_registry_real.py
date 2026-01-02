import logging

import pytest
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.schema_registry_real")


def test_serialize_and_deserialize_event_real_registry(test_settings: Settings) -> None:
    # Uses real Schema Registry configured via env (SCHEMA_REGISTRY_URL)
    m = SchemaRegistryManager(settings=test_settings, logger=_test_logger)
    ev = PodCreatedEvent(
        execution_id="e1",
        pod_name="p",
        namespace="n",
        metadata=AvroEventMetadata(service_name="s", service_version="1"),
    )
    data = m.serialize_event(ev)
    obj = m.deserialize_event(data, topic=str(ev.topic))
    assert isinstance(obj, PodCreatedEvent)
    assert obj.namespace == "n"
