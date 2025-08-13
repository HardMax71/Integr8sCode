import json
from typing import Any, Dict, List, Optional, Tuple, Type

import httpx
from confluent_kafka.schema_registry import Schema, SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext
from pydantic import BaseModel

from app.config import get_settings
from app.core.logging import logger
from app.schemas_avro.event_schemas import BaseEvent, EventType, build_event_type_mapping


class SchemaRegistryManager:
    """Simplified schema registry manager using confluent-kafka libraries"""

    def __init__(self, schema_registry_url: Optional[str] = None):
        settings = get_settings()
        self.url = schema_registry_url or settings.SCHEMA_REGISTRY_URL
        self.namespace = "com.integr8scode.events"

        # Build config for Schema Registry client
        config = {"url": self.url}
        # Only add auth if configured
        if hasattr(settings, 'SCHEMA_REGISTRY_AUTH') and settings.SCHEMA_REGISTRY_AUTH:
            config["basic.auth.user.info"] = settings.SCHEMA_REGISTRY_AUTH
        self.client = SchemaRegistryClient(config)

        # Simple caches for performance
        self._serializers: Dict[str, AvroSerializer] = {}
        self._deserializers: Dict[str, AvroDeserializer] = {}

    def register_schema(self, subject: str, event_class: Type[BaseEvent]) -> int:
        """Register an event class schema with the registry"""
        avro_schema = event_class.avro_schema(namespace=self.namespace)
        schema_str = json.dumps(avro_schema)

        try:
            schema_id: int = self.client.register_schema(subject, Schema(schema_str, "AVRO"))
            logger.info(f"Registered schema for {subject}: ID {schema_id}")
            return schema_id
        except Exception as e:
            logger.error(f"Failed to register schema for {subject}: {e}")
            raise

    def _get_or_create_serializer(self, subject: str, event_class: Type[BaseEvent]) -> AvroSerializer:
        """Get cached or create new serializer"""
        if subject not in self._serializers:
            avro_schema = event_class.avro_schema(namespace=self.namespace)
            schema_str = json.dumps(avro_schema)

            # Register schema first
            self.register_schema(subject, event_class)

            # Create serializer that converts Pydantic models to dicts
            self._serializers[subject] = AvroSerializer(
                self.client,
                schema_str,
                to_dict=lambda obj, ctx: obj.model_dump() if isinstance(obj, BaseModel) else obj
            )

        return self._serializers[subject]

    def _get_or_create_deserializer(self, subject: str, event_class: Type[BaseEvent]) -> AvroDeserializer:
        """Get cached or create new deserializer"""
        if subject not in self._deserializers:
            # Create deserializer that constructs Pydantic models from dicts
            self._deserializers[subject] = AvroDeserializer(
                self.client,
                from_dict=lambda obj, ctx: event_class(**obj)
            )

        return self._deserializers[subject]

    def serialize_event(self, event: BaseEvent, topic: str) -> bytes:
        """Serialize an event to Avro bytes"""
        # Use the standard Confluent subject naming: topic-value
        subject = f"{topic}-value"
        serializer = self._get_or_create_serializer(subject, event.__class__)

        ctx = SerializationContext(topic, MessageField.VALUE)
        serialized_bytes: bytes = serializer(event, ctx)
        return serialized_bytes

    def deserialize_event(self, data: bytes, topic: str, event_class: Type[BaseEvent]) -> BaseEvent:
        """Deserialize Avro bytes to an event"""
        # Use the standard Confluent subject naming: topic-value
        subject = f"{topic}-value"
        deserializer = self._get_or_create_deserializer(subject, event_class)

        ctx = SerializationContext(topic, MessageField.VALUE)
        deserialized_event: BaseEvent = deserializer(data, ctx)
        return deserialized_event

    def deserialize_event_generic(self, data: bytes, topic: str) -> Tuple[Optional[Type[BaseEvent]], Dict[str, Any]]:
        """Deserialize without knowing the event class"""
        # Use a generic deserializer
        generic_deserializer = AvroDeserializer(self.client)
        ctx = SerializationContext(topic, MessageField.VALUE)
        result = generic_deserializer(data, ctx)

        # Determine event class from the data
        event_class = None
        if isinstance(result, dict) and 'event_type' in result:
            try:
                event_type = EventType(result['event_type'])
                event_type_mapping = build_event_type_mapping()
                event_class = event_type_mapping.get(event_type)
            except (ValueError, KeyError):
                logger.warning(f"Unknown event type: {result.get('event_type')}")

        return event_class, result

    def set_compatibility(self, subject: str, mode: str) -> None:
        """Set compatibility mode for a subject"""
        valid_modes = {"BACKWARD", "FORWARD", "FULL", "NONE",
                       "BACKWARD_TRANSITIVE", "FORWARD_TRANSITIVE", "FULL_TRANSITIVE"}

        if mode not in valid_modes:
            raise ValueError(f"Invalid compatibility mode: {mode}")

        url = f"{self.url}/config/{subject}"
        response = httpx.put(url, json={"compatibility": mode})
        response.raise_for_status()
        logger.info(f"Set {subject} compatibility to {mode}")

    async def initialize_schemas(self, event_classes: List[Type[BaseEvent]]) -> None:
        """Initialize all event schemas in the registry"""
        # Create mapping from class name to EventType value (which is the topic)
        topic_mapping = {
            cls.__name__: cls.model_fields['event_type'].default
            for cls in BaseEvent.__subclasses__()
            if 'event_type' in cls.model_fields
        }

        for event_class in event_classes:
            # Get the specific topic for this event type
            topic = topic_mapping.get(event_class.__name__, "events")
            # Use standard Confluent subject naming: topic-value
            subject = f"{topic}-value"
            try:
                # Set forward compatibility for event evolution
                self.set_compatibility(subject, "FORWARD")
                _ = self.register_schema(subject, event_class)
            except Exception as e:
                logger.error(f"Failed to initialize {event_class.__name__}: {e}")


class SchemaRegistryManagerSingleton:
    """Singleton wrapper for SchemaRegistryManager"""
    _instance: Optional[SchemaRegistryManager] = None

    @classmethod
    def get_instance(cls) -> SchemaRegistryManager:
        if cls._instance is None:
            cls._instance = SchemaRegistryManager()
        return cls._instance


def get_schema_registry() -> SchemaRegistryManager:
    """Get schema registry manager instance"""
    return SchemaRegistryManagerSingleton.get_instance()


async def initialize_event_schemas() -> None:
    """Initialize all event schemas in the registry"""
    registry = get_schema_registry()
    event_type_mapping = build_event_type_mapping()
    event_classes = list(event_type_mapping.values())

    await registry.initialize_schemas(event_classes)
    logger.info(f"Initialized {len(event_classes)} event schemas")
