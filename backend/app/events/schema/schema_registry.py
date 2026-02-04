import logging

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
        self._client = AsyncSchemaRegistryClient(url=settings.SCHEMA_REGISTRY_URL)
        self.serializer = AsyncAvroMessageSerializer(self._client)

    async def serialize_event(self, event: DomainEvent) -> bytes:
        """Serialize event to Confluent wire format: [0x00][4-byte schema id][Avro binary]."""
        avro = schema.AvroSchema(event.avro_schema(namespace=self.namespace))
        subject = f"{self.subject_prefix}{avro.name}-value"
        return await self.serializer.encode_record_with_schema(subject, avro, event.model_dump())
