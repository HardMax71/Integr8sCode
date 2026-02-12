from app.domain.enums import EventType
from app.infrastructure.kafka.mappings import get_event_class_for_type


def test_event_class_for_type() -> None:
    cls = get_event_class_for_type(EventType.CREATE_POD_COMMAND)
    assert cls is not None

    cls2 = get_event_class_for_type(EventType.EXECUTION_REQUESTED)
    assert cls2 is not None
