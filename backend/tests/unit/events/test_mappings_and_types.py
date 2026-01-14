from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.mappings import (
    get_event_class_for_type,
    get_event_types_for_topic,
    get_topic_for_event,
)


def test_event_mappings_topics() -> None:
    # A few spot checks
    assert get_topic_for_event(EventType.EXECUTION_REQUESTED) == KafkaTopic.EXECUTION_EVENTS
    cls = get_event_class_for_type(EventType.CREATE_POD_COMMAND)
    assert cls is not None
    # All event types for a topic include at least one of the checked types
    ev_types = get_event_types_for_topic(KafkaTopic.EXECUTION_EVENTS)
    assert EventType.EXECUTION_REQUESTED in ev_types
