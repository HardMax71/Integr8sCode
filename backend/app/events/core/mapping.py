"""
Event type to schema and topic mappings for Kafka.

This module provides compatibility layer for legacy code that uses get_topic_name
and get_schema_name functions. New code should import directly from event_schemas.
"""
from typing import Dict

from app.schemas_avro.event_schemas import EventType, get_topic_for_event

# Build schema mapping based on topic names
EVENT_TYPE_TO_SCHEMA: Dict[str, str] = {}
for event_type in EventType:
    topic = get_topic_for_event(event_type)
    # Schema name is same as topic name
    EVENT_TYPE_TO_SCHEMA[str(event_type)] = topic.value


def get_schema_name(event_type: str | EventType) -> str | None:
    """
    Get the schema name for a given event type.
    
    Args:
        event_type: The event type as string or EventType enum
        
    Returns:
        Schema name if mapping exists, None otherwise
    """
    if isinstance(event_type, EventType):
        event_type = str(event_type)
    return EVENT_TYPE_TO_SCHEMA.get(event_type)


def get_default_schema_mapping() -> Dict[str, str]:
    """
    Get a copy of the default schema mapping.
    
    Returns:
        Dictionary mapping event types to schema names
    """
    return EVENT_TYPE_TO_SCHEMA.copy()


def get_topic_name(event_type: str | EventType) -> str:
    """
    Get the topic name for a given event type.
    
    Args:
        event_type: The event type as string or EventType enum
        
    Returns:
        Topic name if mapping exists, "system_events" as default
    """
    topic = get_topic_for_event(event_type)
    return topic.value
