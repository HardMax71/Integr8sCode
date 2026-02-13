from app.domain.enums import EventType, KafkaTopic
from app.infrastructure.kafka.mappings import (
    get_event_class_for_type,
    get_topic_for_event,
)


def test_event_mappings_topics() -> None:
    # A few spot checks
    assert get_topic_for_event(EventType.EXECUTION_REQUESTED) == KafkaTopic.EXECUTION_EVENTS
    cls = get_event_class_for_type(EventType.CREATE_POD_COMMAND)
    assert cls is not None
