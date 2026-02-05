"""Tests for Kafka topic mappings.

Note: The EventType to event class mapping is deprecated in favor of
1:1 topic mapping where topic names are derived from class names.
"""
from app.domain.events.typed import BaseEvent, ExecutionRequestedEvent


def test_event_class_topic_derivation() -> None:
    """Event classes derive their topic from class name."""
    # Topic is derived from class name: ExecutionRequestedEvent -> execution_requested
    assert ExecutionRequestedEvent.topic() == "execution_requested"

    # BaseEvent itself has topic 'base'
    assert BaseEvent.topic() == "base"


def test_topic_with_prefix() -> None:
    """Topics can have an optional prefix."""
    assert ExecutionRequestedEvent.topic("prefix_") == "prefix_execution_requested"
