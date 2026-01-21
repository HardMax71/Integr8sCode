"""Fake Schema Registry Manager for unit testing."""

import io
import logging
import struct
from functools import lru_cache
from typing import Any, get_args, get_origin

import fastavro
from app.domain.enums.events import EventType
from app.domain.events.typed import DomainEvent
from fastavro.types import Schema

MAGIC_BYTE = b"\x00"


@lru_cache(maxsize=1)
def _get_all_event_classes() -> list[type[DomainEvent]]:
    """Get all concrete event classes from DomainEvent union."""
    union_type = get_args(DomainEvent)[0]  # Annotated[Union[...], Discriminator] -> Union
    return list(get_args(union_type)) if get_origin(union_type) else [union_type]


class FakeSchemaRegistryManager:
    """Fake schema registry manager for unit tests.

    Serializes/deserializes using fastavro without network calls.
    """

    def __init__(self, settings: Any = None, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger(__name__)
        self._schema_id_counter = 0
        self._schema_id_cache: dict[type[DomainEvent], int] = {}
        self._id_to_class_cache: dict[int, type[DomainEvent]] = {}
        self._parsed_schemas: dict[type[DomainEvent], Schema] = {}

    def _get_schema_id(self, event_class: type[DomainEvent]) -> int:
        """Get or assign schema ID for event class."""
        if event_class not in self._schema_id_cache:
            self._schema_id_counter += 1
            self._schema_id_cache[event_class] = self._schema_id_counter
            self._id_to_class_cache[self._schema_id_counter] = event_class
        return self._schema_id_cache[event_class]

    def _get_parsed_schema(self, event_class: type[DomainEvent]) -> Schema:
        """Get or parse Avro schema for event class."""
        if event_class not in self._parsed_schemas:
            avro_schema = event_class.avro_schema_to_python()
            self._parsed_schemas[event_class] = fastavro.parse_schema(avro_schema)
        return self._parsed_schemas[event_class]

    async def serialize_event(self, event: DomainEvent) -> bytes:
        """Serialize event to Confluent wire format."""
        event_class = event.__class__
        schema_id = self._get_schema_id(event_class)
        parsed_schema = self._get_parsed_schema(event_class)

        # Prepare payload
        payload: dict[str, Any] = event.model_dump(mode="python", by_alias=False, exclude_unset=False)
        payload.pop("event_type", None)

        # Convert datetime to microseconds for Avro logical type
        if "timestamp" in payload and payload["timestamp"] is not None:
            payload["timestamp"] = int(payload["timestamp"].timestamp() * 1_000_000)

        # Serialize with fastavro
        buffer = io.BytesIO()
        fastavro.schemaless_writer(buffer, parsed_schema, payload)
        avro_bytes = buffer.getvalue()

        # Confluent wire format: [0x00][4-byte schema id BE][Avro binary]
        return MAGIC_BYTE + struct.pack(">I", schema_id) + avro_bytes

    async def deserialize_event(self, data: bytes, topic: str) -> DomainEvent:
        """Deserialize from Confluent wire format to DomainEvent."""
        if not data or len(data) < 5:
            raise ValueError("Invalid message: too short for wire format")
        if data[0:1] != MAGIC_BYTE:
            raise ValueError(f"Unknown magic byte: {data[0]:#x}")

        schema_id = struct.unpack(">I", data[1:5])[0]
        event_class = self._id_to_class_cache.get(schema_id)
        if not event_class:
            raise ValueError(f"Unknown schema ID: {schema_id}")

        parsed_schema = self._get_parsed_schema(event_class)
        buffer = io.BytesIO(data[5:])
        obj = fastavro.schemaless_reader(buffer, parsed_schema, parsed_schema)

        if not isinstance(obj, dict):
            raise ValueError(f"Deserialization returned {type(obj)}, expected dict")

        # Restore event_type if missing
        if (f := event_class.model_fields.get("event_type")) and f.default and "event_type" not in obj:
            obj["event_type"] = f.default

        return event_class.model_validate(obj)

    def deserialize_json(self, data: dict[str, Any]) -> DomainEvent:
        """Deserialize JSON data to DomainEvent using event_type field."""
        if not (event_type_str := data.get("event_type")):
            raise ValueError("Missing event_type in event data")
        mapping = {cls.model_fields["event_type"].default: cls for cls in _get_all_event_classes()}
        if not (event_class := mapping.get(EventType(event_type_str))):
            raise ValueError(f"No event class found for event type: {event_type_str}")
        return event_class.model_validate(data)

    async def set_compatibility(self, subject: str, mode: str) -> None:
        """No-op for fake."""
        pass

    async def initialize_schemas(self) -> None:
        """Pre-register all schemas."""
        for event_class in _get_all_event_classes():
            self._get_schema_id(event_class)
            self._get_parsed_schema(event_class)
