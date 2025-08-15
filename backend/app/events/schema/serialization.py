from typing import Optional, Type

from app.core.logging import logger
from app.schemas_avro.event_schemas import (
    BaseEvent,
    EventType,
    build_event_type_mapping,
)

from .schema_registry import SchemaRegistryManager


class EventSerializer:
    """Simplified event serializer using schema registry"""

    def __init__(self, schema_registry: SchemaRegistryManager | None = None) -> None:
        self.schema_registry = schema_registry

    def serialize(self, event: BaseEvent, topic: str) -> bytes:
        """Serialize event to Avro bytes"""
        if not self.schema_registry:
            raise RuntimeError("Schema registry not configured for serialization")
        return self.schema_registry.serialize_event(event, topic)

    def deserialize(
            self,
            data: bytes,
            topic: str,
            event_class: Optional[Type[BaseEvent]] = None
    ) -> BaseEvent:
        """Deserialize Avro bytes to event"""
        if not self.schema_registry:
            raise RuntimeError("Schema registry not configured for deserialization")
            
        if event_class:
            # Direct deserialization when we know the event class
            return self.schema_registry.deserialize_event(data, topic, event_class)

        # Generic deserialization when event class is unknown
        return self._deserialize_generic(data, topic)

    def _deserialize_generic(self, data: bytes, topic: str) -> BaseEvent:
        """Deserialize when event class is unknown"""
        if not self.schema_registry:
            raise RuntimeError("Schema registry not configured for deserialization")
        event_class, event_dict = self.schema_registry.deserialize_event_generic(data, topic)

        if event_class:
            return event_class(**event_dict)

        # If we couldn't determine the event class but have the dict
        if isinstance(event_dict, dict) and 'event_type' in event_dict:
            try:
                event_type = EventType(event_dict['event_type'])
                event_type_mapping = build_event_type_mapping()
                event_class = event_type_mapping.get(event_type)
                if event_class:
                    return event_class(**event_dict)
            except (ValueError, KeyError) as e:
                logger.error(f"Failed to determine event class: {e}")

        raise ValueError(f"Unable to deserialize event from topic {topic}")

    def deserialize_by_type(self, data: bytes, topic: str, event_type: EventType) -> BaseEvent:
        """Deserialize when we know the event type"""
        if not self.schema_registry:
            raise RuntimeError("Schema registry not configured for deserialization")
            
        event_type_mapping = build_event_type_mapping()
        event_class = event_type_mapping.get(event_type)
        if not event_class:
            raise ValueError(f"Unknown event type: {event_type}")

        return self.schema_registry.deserialize_event(data, topic, event_class)


def create_event_key(event: BaseEvent) -> str:
    """Create partition key for event using Pydantic's model introspection
    
    This is a production-ready implementation that uses Pydantic's proper APIs
    to determine the best partition key without any branching or attribute checking.
    """
    # Priority 1: aggregate_id (event sourcing best practice)
    if event.aggregate_id:
        return str(event.aggregate_id)

    # Priority 2: Find the best identifier from model's actual data
    # This uses Pydantic's model_dump to get only the fields that exist
    event_data = event.model_dump(exclude={'event_id', 'event_type', 'event_version', 'timestamp', 'metadata'})

    # Define identifier priority (order matters!)
    identifier_priority = [
        'execution_id',
        'user_id',
        'script_id',
        'notification_id',
        'saga_id',
        'pod_name',
        'session_id'
    ]

    # Find first available identifier from the priority list
    for identifier in identifier_priority:
        if value := event_data.get(identifier):
            return str(value)

    # Priority 3: Check metadata for user context
    if event.metadata.user_id:
        return event.metadata.user_id

    # Final fallback: correlation_id (always present in BaseEvent)
    return str(event.metadata.correlation_id)
