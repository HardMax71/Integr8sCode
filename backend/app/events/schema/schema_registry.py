import logging
from typing import Any

from schema_registry.client import AsyncSchemaRegistryClient, schema
from schema_registry.serializers import AsyncAvroMessageSerializer  # type: ignore[attr-defined]

from app.domain.events.typed import DomainEvent
from app.settings import Settings


class SchemaRegistryManager:
    """Avro serialization via Confluent Schema Registry.

    Schemas are registered lazily by the underlying serializer on first
    produce — no eager bootstrap needed.
    """

    def __init__(self, settings: Settings, logger: logging.Logger):
        self.logger = logger
        self.namespace = "com.integr8scode.events"
        self.subject_prefix = settings.SCHEMA_SUBJECT_PREFIX
        parts = settings.SCHEMA_REGISTRY_AUTH.split(":", 1)
        auth: tuple[str, str] | None = (parts[0], parts[1]) if len(parts) == 2 else None
        self._client = AsyncSchemaRegistryClient(url=settings.SCHEMA_REGISTRY_URL, auth=auth)  # type: ignore[arg-type]
        self.serializer = AsyncAvroMessageSerializer(self._client)

    async def serialize_event(self, event: DomainEvent) -> bytes:
        """Serialize event to Confluent wire format: [0x00][4-byte schema id][Avro binary]."""
        subject = f"{self.subject_prefix}{event.__class__.__name__}-value"
        avro_schema = schema.AvroSchema(event.__class__.avro_schema(namespace=self.namespace))
        payload: dict[str, Any] = event.model_dump(mode="python", by_alias=False, exclude_unset=False)
        return await self.serializer.encode_record_with_schema(subject, avro_schema, payload)
