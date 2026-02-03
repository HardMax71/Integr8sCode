import logging
from typing import Any

from faststream import StreamMessage
from faststream.kafka import KafkaBroker

from app.domain.events.typed import DomainEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings


def create_avro_decoder(
    schema_registry: SchemaRegistryManager,
) -> Any:
    """Create a custom Avro decoder closure for FastStream subscribers.

    The decoder receives a StreamMessage whose body is Confluent wire-format
    Avro bytes (magic byte + 4-byte schema ID + Avro payload). We delegate
    deserialization to SchemaRegistryManager which resolves the schema from
    the registry and decodes into the concrete DomainEvent subclass.
    """

    async def avro_decoder(msg: StreamMessage[Any]) -> DomainEvent:
        return await schema_registry.deserialize_event(msg.body, msg.raw_message.topic)

    return avro_decoder


def create_broker(
    settings: Settings,
    schema_registry: SchemaRegistryManager,
    logger: logging.Logger,
) -> KafkaBroker:
    """Create a KafkaBroker with Avro decoder for standalone workers."""
    return KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        decoder=create_avro_decoder(schema_registry),
        logger=logger,
    )
