"""Kafka infrastructure.

Topic routing is handled by FastStream via BaseEvent.topic() method.
This package provides infrastructure-level Kafka utilities.
"""

from app.domain.enums.kafka import GroupId, KafkaTopic
from app.domain.events.typed import BaseEvent, EventMetadata

__all__ = [
    "BaseEvent",
    "EventMetadata",
    "GroupId",
    "KafkaTopic",
]
