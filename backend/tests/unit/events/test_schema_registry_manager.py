import pytest

from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent


def test_deserialize_json_execution_requested() -> None:
    m = SchemaRegistryManager(schema_registry_url="http://dummy")

    data = {
        "event_type": "execution_requested",
        "execution_id": "e1",
        "script": "print('ok')",
        "language": "python",
        "language_version": "3.11",
        "runtime_image": "python:3.11-slim",
        "runtime_command": ["python"],
        "runtime_filename": "main.py",
        "timeout_seconds": 30,
        "cpu_limit": "100m",
        "memory_limit": "128Mi",
        "cpu_request": "50m",
        "memory_request": "64Mi",
        "priority": 5,
        "metadata": {
            "service_name": "t",
            "service_version": "1.0",
        },
    }

    ev = m.deserialize_json(data)
    assert isinstance(ev, ExecutionRequestedEvent)
    assert ev.execution_id == "e1"
    assert ev.language == "python"


def test_deserialize_json_missing_type_raises() -> None:
    m = SchemaRegistryManager(schema_registry_url="http://dummy")
    with pytest.raises(ValueError):
        m.deserialize_json({})
import struct

import pytest

from app.events.schema.schema_registry import MAGIC_BYTE, SchemaRegistryManager
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


class DummyClient:
    def __init__(self):
        self.registered = {}
    def register_schema(self, subject, schema):  # noqa: ANN001
        self.registered[subject] = schema
        return 1
    def get_schema(self, schema_id):  # noqa: ANN001
        # Return a minimal object with schema_str containing a name
        return type("S", (), {"schema_str": '{"type":"record","name":"PodCreatedEvent"}'})()


class DummySerializer:
    def __init__(self, client, schema_str):  # noqa: ANN001
        self.client = client
        self.schema_str = schema_str
    def __call__(self, payload, ctx):  # noqa: ANN001
        return MAGIC_BYTE + struct.pack(">I", 1) + b"payload"


class DummyDeserializer:
    def __call__(self, data, ctx):  # noqa: ANN001
        return {
            "execution_id": "e1",
            "pod_name": "p",
            "namespace": "n",
            "metadata": {"service_name": "s", "service_version": "1"},
        }


def mk_event():
    return PodCreatedEvent(
        execution_id="e1",
        pod_name="p",
        namespace="n",
        metadata=EventMetadata(service_name="s", service_version="1"),
    )


def test_register_and_get_schema_id(monkeypatch):
    m = SchemaRegistryManager(schema_registry_url="http://dummy")
    m.client = DummyClient()  # type: ignore[assignment]
    sid = m.register_schema("PodCreatedEvent-value", PodCreatedEvent)
    assert sid == 1
    assert m._get_schema_id(PodCreatedEvent) == 1


def test_serialize_and_deserialize_event(monkeypatch):
    m = SchemaRegistryManager(schema_registry_url="http://dummy")
    m.client = DummyClient()  # type: ignore[assignment]
    # Patch AvroSerializer/Deserializer
    import app.events.schema.schema_registry as sr
    monkeypatch.setattr(sr, "AvroSerializer", DummySerializer)
    # Set our instance deserializer
    m._deserializer = DummyDeserializer()
    # Serialize
    data = m.serialize_event(mk_event())
    assert data.startswith(MAGIC_BYTE)
    # Map id->class so deserialize_event won't call client.get_schema
    m._id_to_class_cache[1] = PodCreatedEvent
    obj = m.deserialize_event(data, topic="pod_events")
    assert isinstance(obj, PodCreatedEvent)
    assert obj.namespace == "n"


def test_set_compatibility(monkeypatch):
    m = SchemaRegistryManager(schema_registry_url="http://dummy")
    class Resp:
        def raise_for_status(self):
            return None
    import httpx
    monkeypatch.setattr(httpx, "put", lambda url, json: Resp())
    m.set_compatibility("subj", "FORWARD")

