import logging
import struct
from functools import lru_cache
from typing import Any, get_args, get_origin

from schema_registry.client import AsyncSchemaRegistryClient, schema
from schema_registry.serializers import AsyncAvroMessageSerializer  # type: ignore[attr-defined]

from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from app.settings import Settings

MAGIC_BYTE = b"\x00"


@lru_cache(maxsize=1)
def _get_all_event_classes() -> list[type[DomainEvent]]:
    """Get all concrete event classes from DomainEvent union."""
    union_type = get_args(DomainEvent)[0]  # Annotated[Union[...], Discriminator] -> Union
    return list(get_args(union_type)) if get_origin(union_type) else [union_type]


@lru_cache(maxsize=1)
def _get_event_class_mapping() -> dict[str, type[DomainEvent]]:
    """Map class name -> class."""
    return {cls.__name__: cls for cls in _get_all_event_classes()}


@lru_cache(maxsize=1)
def _get_event_type_to_class_mapping() -> dict[EventType, type[DomainEvent]]:
    """EventType -> class mapping."""
    return {cls.model_fields["event_type"].default: cls for cls in _get_all_event_classes()}


class SchemaRegistryManager:
    """Schema registry manager for Avro serialization with Confluent wire format."""

    def __init__(self, settings: Settings, logger: logging.Logger):
        self.logger = logger
        self.namespace = "com.integr8scode.events"
        self.subject_prefix = settings.SCHEMA_SUBJECT_PREFIX
        parts = settings.SCHEMA_REGISTRY_AUTH.split(":", 1)
        auth: tuple[str, str] | None = (parts[0], parts[1]) if len(parts) == 2 else None
        self._client = AsyncSchemaRegistryClient(url=settings.SCHEMA_REGISTRY_URL, auth=auth)  # type: ignore[arg-type]
        self._serializer = AsyncAvroMessageSerializer(self._client)
        self._schema_id_cache: dict[type[DomainEvent], int] = {}
        self._id_to_class_cache: dict[int, type[DomainEvent]] = {}

    async def register_schema(self, subject: str, event_class: type[DomainEvent]) -> int:
        """Register schema and return schema ID."""
        avro_schema = schema.AvroSchema(event_class.avro_schema(namespace=self.namespace))
        schema_id: int = await self._client.register(subject, avro_schema)
        self._schema_id_cache[event_class] = schema_id
        self._id_to_class_cache[schema_id] = event_class
        self.logger.info(f"Registered schema for {event_class.__name__}: ID {schema_id}")
        return schema_id

    async def _get_event_class_by_id(self, schema_id: int) -> type[DomainEvent] | None:
        """Get event class by schema ID."""
        if schema_id in self._id_to_class_cache:
            return self._id_to_class_cache[schema_id]
        schema_obj = await self._client.get_by_id(schema_id)
        if schema_obj and (class_name := schema_obj.raw_schema.get("name")):
            if cls := _get_event_class_mapping().get(class_name):
                self._id_to_class_cache[schema_id] = cls
                self._schema_id_cache[cls] = schema_id
                return cls
        return None

    async def serialize_event(self, event: DomainEvent) -> bytes:
        """Serialize event to Confluent wire format: [0x00][4-byte schema id][Avro binary]."""
        subject = f"{self.subject_prefix}{event.__class__.__name__}-value"
        avro_schema = schema.AvroSchema(event.__class__.avro_schema(namespace=self.namespace))
        payload: dict[str, Any] = event.model_dump(mode="python", by_alias=False, exclude_unset=False)
        payload.pop("event_type", None)
        if "timestamp" in payload and payload["timestamp"] is not None:
            payload["timestamp"] = int(payload["timestamp"].timestamp() * 1_000_000)
        return await self._serializer.encode_record_with_schema(subject, avro_schema, payload)

    async def deserialize_event(self, data: bytes, topic: str) -> DomainEvent:
        """Deserialize from Confluent wire format to DomainEvent."""
        if not data or len(data) < 5:
            raise ValueError("Invalid message: too short for wire format")
        if data[0:1] != MAGIC_BYTE:
            raise ValueError(f"Unknown magic byte: {data[0]:#x}")
        schema_id = struct.unpack(">I", data[1:5])[0]
        event_class = await self._get_event_class_by_id(schema_id)
        if not event_class:
            raise ValueError(f"Unknown schema ID: {schema_id}")
        obj = await self._serializer.decode_message(data)
        if not isinstance(obj, dict):
            raise ValueError(f"Deserialization returned {type(obj)}, expected dict")
        if (f := event_class.model_fields.get("event_type")) and f.default and "event_type" not in obj:
            obj["event_type"] = f.default
        return event_class.model_validate(obj)

    def deserialize_json(self, data: dict[str, Any]) -> DomainEvent:
        """Deserialize JSON data to DomainEvent using event_type field."""
        if not (event_type_str := data.get("event_type")):
            raise ValueError("Missing event_type in event data")
        if not (event_class := _get_event_type_to_class_mapping().get(EventType(event_type_str))):
            raise ValueError(f"No event class found for event type: {event_type_str}")
        return event_class.model_validate(data)

    async def set_compatibility(self, subject: str, mode: str) -> None:
        """Set compatibility for a subject."""
        valid = {"BACKWARD", "FORWARD", "FULL", "NONE", "BACKWARD_TRANSITIVE", "FORWARD_TRANSITIVE", "FULL_TRANSITIVE"}
        if mode not in valid:
            raise ValueError(f"Invalid compatibility mode: {mode}")
        await self._client.update_compatibility(level=mode, subject=subject)
        self.logger.info(f"Set {subject} compatibility to {mode}")

    async def initialize_schemas(self) -> None:
        """Initialize all event schemas in the registry."""
        for event_class in _get_all_event_classes():
            subject = f"{self.subject_prefix}{event_class.__name__}-value"
            await self.set_compatibility(subject, "FORWARD")
            await self.register_schema(subject, event_class)
        self.logger.info(f"Initialized {len(_get_all_event_classes())} event schemas")


async def initialize_event_schemas(registry: SchemaRegistryManager) -> None:
    await registry.initialize_schemas()
