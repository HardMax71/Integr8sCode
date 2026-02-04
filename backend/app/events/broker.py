import logging
from typing import Any

from faststream import StreamMessage
from faststream.kafka import KafkaBroker

from app.domain.events.typed import DomainEvent, DomainEventAdapter
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings


def create_broker(
    settings: Settings,
    schema_registry: SchemaRegistryManager,
    logger: logging.Logger,
) -> KafkaBroker:
    """Create a KafkaBroker with Avro decoder for standalone workers."""

    async def avro_decoder(msg: StreamMessage[Any]) -> DomainEvent:
        payload = await schema_registry.serializer.decode_message(msg.body)
        return DomainEventAdapter.validate_python(payload)

    return KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        decoder=avro_decoder,
        logger=logger,
    )
