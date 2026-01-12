import logging
import struct
from functools import lru_cache
from typing import Any, Dict, Type, TypeVar

from schema_registry.client import AsyncSchemaRegistryClient, schema
from schema_registry.serializers import AsyncAvroMessageSerializer  # type: ignore[attr-defined]

from app.domain.enums.events import EventType
from app.infrastructure.kafka.events.base import BaseEvent
from app.settings import Settings

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
    EventType enum -> event class, inferred from the default of the `event_type` field on each subclass.
    """
    mapping: Dict[EventType, Type[BaseEvent]] = {}
    for subclass in _get_all_event_classes():
        f = subclass.model_fields.get("event_type")
        if f is not None and f.default is not None:
            mapping[f.default] = subclass  # default is EventType thanks to Literal[...]
    return mapping


class SchemaRegistryManager:
    """Schema registry manager for Avro serialization with Confluent wire format.

    Uses aiokafka-compatible python-schema-registry-client for fully async operations.
    """

    def __init__(self, settings: Settings, logger: logging.Logger):
        self.logger = logger
        self.namespace = "com.integr8scode.events"
        self.subject_prefix = settings.SCHEMA_SUBJECT_PREFIX

        parts = settings.SCHEMA_REGISTRY_AUTH.split(":", 1)
        auth: tuple[str, str] | None = (parts[0], parts[1]) if len(parts) == 2 else None
        self._client = AsyncSchemaRegistryClient(url=settings.SCHEMA_REGISTRY_URL, auth=auth)  # type: ignore[arg-type]
        self._serializer = AsyncAvroMessageSerializer(self._client)

        # Caches: class <-> schema_id (library caches schema_string -> id, we need class -> id)
        self._schema_id_cache: Dict[Type[BaseEvent], int] = {}
        self._id_to_class_cache: Dict[int, Type[BaseEvent]] = {}

    async def register_schema(self, subject: str, event_class: Type[BaseEvent]) -> int:
        """Register schema and return schema ID."""
        avro_schema = schema.AvroSchema(event_class.avro_schema(namespace=self.namespace))
        schema_id: int = await self._client.register(subject, avro_schema)
        self._schema_id_cache[event_class] = schema_id
        self._id_to_class_cache[schema_id] = event_class
        self.logger.info(f"Registered schema for {event_class.__name__}: ID {schema_id}")
        return schema_id

    async def _get_schema_id(self, event_class: Type[BaseEvent]) -> int:
        """Get or register schema ID for event class."""
        if event_class in self._schema_id_cache:
            return self._schema_id_cache[event_class]
        subject = f"{self.subject_prefix}{event_class.__name__}-value"
        return await self.register_schema(subject, event_class)

    async def _get_event_class_by_id(self, schema_id: int) -> Type[BaseEvent] | None:
        """Get event class by schema ID, via cache or registry lookup."""
        if schema_id in self._id_to_class_cache:
            return self._id_to_class_cache[schema_id]

        schema_obj = await self._client.get_by_id(schema_id)
        if schema_obj is None:
            return None

        # Parse schema to get class name - raw_schema is already a dict
        schema_dict = schema_obj.raw_schema
        class_name = schema_dict.get("name")
        if class_name:
            cls = _get_event_class_mapping().get(class_name)
            if cls:
                self._id_to_class_cache[schema_id] = cls
                self._schema_id_cache[cls] = schema_id
                return cls

        return None

    async def serialize_event(self, event: BaseEvent) -> bytes:
        """
        Serialize event to Confluent wire format.
        Format: [0x00][4-byte schema id][Avro binary]
        """
        subject = f"{self.subject_prefix}{event.__class__.__name__}-value"
        avro_schema = schema.AvroSchema(event.__class__.avro_schema(namespace=self.namespace))

        # Prepare payload dict (exclude event_type: schema id implies the concrete record)
        payload: dict[str, Any] = event.model_dump(mode="python", by_alias=False, exclude_unset=False)
        payload.pop("event_type", None)

        # Convert datetime to microseconds for Avro timestamp-micros logical type
        if "timestamp" in payload and payload["timestamp"] is not None:
            payload["timestamp"] = int(payload["timestamp"].timestamp() * 1_000_000)

        return await self._serializer.encode_record_with_schema(subject, avro_schema, payload)

    async def deserialize_event(self, data: bytes, topic: str) -> BaseEvent:
        """
        Deserialize from Confluent wire format to a concrete BaseEvent subclass.
        """
        if not data or len(data) < 5:
            raise ValueError("Invalid message: too short for wire format")

        if data[0:1] != MAGIC_BYTE:
            raise ValueError(f"Unknown magic byte: {data[0]:#x}")

        # Extract schema ID from wire format
        schema_id = struct.unpack(">I", data[1:5])[0]
        event_class = await self._get_event_class_by_id(schema_id)
        if not event_class:
            raise ValueError(f"Unknown schema ID: {schema_id}")

        # Decode the message
        obj = await self._serializer.decode_message(data)
        if not isinstance(obj, dict):
            raise ValueError(f"Deserialization returned {type(obj)}, expected dict")

        # Restore constant event_type if schema/payload doesn't include it
        f = event_class.model_fields.get("event_type")
        if f is not None and f.default is not None and "event_type" not in obj:
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

    async def set_compatibility(self, subject: str, mode: str) -> None:
        """
        Set compatibility for a subject.
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

        await self._client.update_compatibility(level=mode, subject=subject)
        self.logger.info(f"Set {subject} compatibility to {mode}")

    async def initialize_schemas(self) -> None:
        """Initialize all event schemas in the registry (set compat + register)."""
        for event_class in _get_all_event_classes():
            subject = f"{self.subject_prefix}{event_class.__name__}-value"
            await self.set_compatibility(subject, "FORWARD")
            await self.register_schema(subject, event_class)

        self.logger.info(f"Initialized {len(_get_all_event_classes())} event schemas")


async def initialize_event_schemas(registry: SchemaRegistryManager) -> None:
    await registry.initialize_schemas()
