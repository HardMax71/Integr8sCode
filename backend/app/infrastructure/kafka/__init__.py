"""Kafka infrastructure for event-driven architecture."""

from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.infrastructure.kafka.mappings import get_event_class_for_type, get_topic_for_event
from app.infrastructure.kafka.topics import get_all_topics, get_topic_configs

__all__ = [
    "BaseEvent",
    "EventMetadata",
    "get_all_topics",
    "get_topic_configs",
    "get_event_class_for_type",
    "get_topic_for_event",
]
