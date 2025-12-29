import json
import logging
import os
import struct
from functools import lru_cache
from typing import Any, Dict, Type, TypeVar

import httpx
from confluent_kafka.schema_registry import Schema, SchemaRegistryClient, record_subject_name_strategy
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from app.domain.enums.events import EventType
from app.infrastructure.kafka.events.base import BaseEvent
from app.settings import get_settings

T = TypeVar("T", bound=BaseEvent)

# Confluent wire-format magic byte (single byte, value 0)
MAGIC_BYTE = b"\x00"


@lru_cache(maxsize=1)
def _get_event_class_mapping() -> Dict[str, Type[BaseEvent]]:
    """
    Map Avro record name (class name) -> Python class.
    Uses only direct subclasses; extend to recursive if you introduce deeper hierarchies.
    """
    mapping: Dict[str, Type[BaseEvent]] = {}
    for subclass in BaseEvent.__subclasses__():
        mapping[subclass.__name__] = subclass
    return mapping


@lru_cache(maxsize=1)
def _get_all_event_classes() -> list[Type[BaseEvent]]:
    """All direct subclasses of BaseEvent (extend to recursive IF you add nested inheritance)."""
    return list(BaseEvent.__subclasses__())


@lru_cache(maxsize=1)
def _get_event_type_to_class_mapping() -> Dict[EventType, Type[BaseEvent]]:
    """
    EventType enum → event class, inferred from the default of the `event_type` field on each subclass.
    """
    mapping: Dict[EventType, Type[BaseEvent]] = {}
    for subclass in _get_all_event_classes():
        f = subclass.model_fields.get("event_type")
        if f is not None and f.default is not None:
            mapping[f.default] = subclass  # default is EventType thanks to Literal[…]
    return mapping


class SchemaRegistryManager:
    """Schema registry manager for Avro serialization with Confluent wire format."""

    def __init__(self, logger: logging.Logger, schema_registry_url: str | None = None):
        self.logger = logger
        settings = get_settings()
        self.url = schema_registry_url or settings.SCHEMA_REGISTRY_URL
        self.namespace = "com.integr8scode.events"
        # Optional per-session/worker subject prefix for tests/local isolation
        # e.g., "test.<session>.<worker>." -> subjects become "test.x.y.ExecutionRequestedEvent-value"
        self.subject_prefix = os.getenv("SCHEMA_SUBJECT_PREFIX", "")

        config = {"url": self.url}
        if settings.SCHEMA_REGISTRY_AUTH:
            config["basic.auth.user.info"] = settings.SCHEMA_REGISTRY_AUTH
        self.client = SchemaRegistryClient(config)

        # Caches
        self._serializers: Dict[str, AvroSerializer] = {}  # subject -> serializer
        self._deserializer: AvroDeserializer | None = None  # single, returns dict
        self._schema_id_cache: Dict[Type[BaseEvent], int] = {}  # class -> schema id
        self._id_to_class_cache: Dict[int, Type[BaseEvent]] = {}  # schema id -> class
        self._initialized = False

    def register_schema(self, subject: str, event_class: Type[BaseEvent]) -> int:
        avro_schema = event_class.avro_schema(namespace=self.namespace)
        schema_str = json.dumps(avro_schema)

        schema_id: int = self.client.register_schema(subject, Schema(schema_str, "AVRO"))
        self._schema_id_cache[event_class] = schema_id
        self._id_to_class_cache[schema_id] = event_class
        self.logger.info(f"Registered schema for {event_class.__name__}: ID {schema_id}")
        return schema_id

    def _get_schema_id(self, event_class: Type[BaseEvent]) -> int:
        """Get or register schema ID for event class."""
        if event_class in self._schema_id_cache:
            return self._schema_id_cache[event_class]
        # Use event class name in subject with optional prefix for test isolation
        subject = f"{self.subject_prefix}{event_class.__name__}-value"
        return self.register_schema(subject, event_class)

    def _get_event_class_by_id(self, schema_id: int) -> Type[BaseEvent] | None:
        """Get event class by schema ID, via cache or registry lookup of the writer schema name."""
        if schema_id in self._id_to_class_cache:
            return self._id_to_class_cache[schema_id]

        schema = self.client.get_schema(schema_id)
        schema_dict = json.loads(str(schema.schema_str))

        class_name = schema_dict.get("name")
        if class_name:
            cls = _get_event_class_mapping().get(class_name)
            if cls:
                self._id_to_class_cache[schema_id] = cls
                self._schema_id_cache[cls] = schema_id
                return cls

        return None

    def serialize_event(self, event: BaseEvent) -> bytes:
        """
        Serialize event to Confluent wire format.
        AvroSerializer already emits: [0x00][4-byte schema id][Avro binary].  (No manual packing)
        """
        # Ensure schema is registered & id cached (keeps id<->class mapping warm)
        self._get_schema_id(event.__class__)

        # Subject-key for serializer cache (include optional prefix for isolation)
        subject_key = f"{self.subject_prefix}{event.__class__.__name__}-value"
        if subject_key not in self._serializers:
            schema_str = json.dumps(event.__class__.avro_schema(namespace=self.namespace))
            # Use record_subject_name_strategy to ensure subject is based on record name, not topic
            self._serializers[subject_key] = AvroSerializer(
                self.client, schema_str, conf={"subject.name.strategy": record_subject_name_strategy}
            )

        # Prepare payload dict (exclude event_type: schema id implies the concrete record)
        # Don't use mode="json" as it converts datetime to string, breaking Avro timestamp-micros
        payload: dict[str, Any] = event.model_dump(mode="python", by_alias=False, exclude_unset=False)
        payload.pop("event_type", None)

        # Convert datetime to microseconds for Avro timestamp-micros logical type
        if "timestamp" in payload and payload["timestamp"] is not None:
            payload["timestamp"] = int(payload["timestamp"].timestamp() * 1_000_000)

        ctx = SerializationContext(str(event.topic), MessageField.VALUE)
        data = self._serializers[subject_key](payload, ctx)  # returns framed bytes (magic+id+payload)
        if data is None:
            raise ValueError("Serialization returned None")
        return data

    def deserialize_event(self, data: bytes, topic: str) -> BaseEvent:
        """
        Deserialize from Confluent wire format to a concrete BaseEvent subclass.
        - Parse header to get schema id → resolve event class
        - Use a single AvroDeserializer (no from_dict) to get a dict
        - Hydrate Pydantic model and restore constant event_type, if omitted from payload
        """
        if not data or len(data) < 5:
            raise ValueError("Invalid message: too short for wire format")

        if data[0:1] != MAGIC_BYTE:
            raise ValueError(f"Unknown magic byte: {data[0]:#x}")

        schema_id = struct.unpack(">I", data[1:5])[0]
        event_class = self._get_event_class_by_id(schema_id)
        if not event_class:
            raise ValueError(f"Unknown schema ID: {schema_id}")

        if self._deserializer is None:
            self._deserializer = AvroDeserializer(self.client)  # returns dict when no from_dict is provided

        ctx = SerializationContext(topic or "unknown", MessageField.VALUE)
        obj = self._deserializer(data, ctx)
        if not isinstance(obj, dict):
            raise ValueError(f"Deserialization returned {type(obj)}, expected dict")

        # Restore constant event_type if schema/payload doesn't include it
        f = event_class.model_fields.get("event_type")
        if f is not None and f.default is not None and "event_type" not in obj:
            # f.default is already the EventType enum which is what we want
            obj["event_type"] = f.default

        return event_class.model_validate(obj)

    def deserialize_json(self, data: dict[str, Any]) -> BaseEvent:
        """
        Deserialize JSON data (from MongoDB or DLQ) to event object using event_type field.
        """
        event_type_str = data.get("event_type")
        if not event_type_str:
            raise ValueError("Missing event_type in event data")

        event_type = EventType(event_type_str)
        mapping = _get_event_type_to_class_mapping()
        event_class = mapping.get(event_type)

        if not event_class:
            raise ValueError(f"No event class found for event type: {event_type}")

        return event_class.model_validate(data)

    def set_compatibility(self, subject: str, mode: str) -> None:
        """
        Set compatibility for a subject via REST API.
        Valid: BACKWARD, FORWARD, FULL, NONE, BACKWARD_TRANSITIVE, FORWARD_TRANSITIVE, FULL_TRANSITIVE
        """
        valid_modes = {
            "BACKWARD",
            "FORWARD",
            "FULL",
            "NONE",
            "BACKWARD_TRANSITIVE",
            "FORWARD_TRANSITIVE",
            "FULL_TRANSITIVE",
        }
        if mode not in valid_modes:
            raise ValueError(f"Invalid compatibility mode: {mode}")

        url = f"{self.url}/config/{subject}"
        response = httpx.put(url, json={"compatibility": mode})
        response.raise_for_status()
        self.logger.info(f"Set {subject} compatibility to {mode}")

    async def initialize_schemas(self) -> None:
        """Initialize all event schemas in the registry (set compat + register)."""
        if self._initialized:
            return

        for event_class in _get_all_event_classes():
            # Use event class name with optional prefix for per-run isolation in tests
            subject = f"{self.subject_prefix}{event_class.__name__}-value"
            self.set_compatibility(subject, "FORWARD")
            self.register_schema(subject, event_class)

        self._initialized = True
        self.logger.info(f"Initialized {len(_get_all_event_classes())} event schemas")


def create_schema_registry_manager(logger: logging.Logger, schema_registry_url: str | None = None) -> SchemaRegistryManager:
    return SchemaRegistryManager(logger, schema_registry_url)


async def initialize_event_schemas(registry: SchemaRegistryManager) -> None:
    await registry.initialize_schemas()
