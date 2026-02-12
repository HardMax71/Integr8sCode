from functools import lru_cache
from typing import get_args, get_origin

from app.domain.enums import EventType, GroupId

CONSUMER_GROUP_SUBSCRIPTIONS: dict[GroupId, set[EventType]] = {
    GroupId.EXECUTION_COORDINATOR: {
        EventType.EXECUTION_REQUESTED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_CANCELLED,
    },
    GroupId.K8S_WORKER: {
        EventType.CREATE_POD_COMMAND,
        EventType.DELETE_POD_COMMAND,
    },
    GroupId.RESULT_PROCESSOR: {
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    },
    GroupId.SAGA_ORCHESTRATOR: {
        EventType.EXECUTION_REQUESTED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    },
    GroupId.NOTIFICATION_SERVICE: {
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
    },
}


@lru_cache(maxsize=1)
def _get_event_type_to_class() -> dict[EventType, type]:
    """Build mapping from EventType to event class using DomainEvent union."""
    from app.domain.events.typed import DomainEvent

    union_type = get_args(DomainEvent)[0]
    classes = list(get_args(union_type)) if get_origin(union_type) is not None else [union_type]
    return {cls.model_fields["event_type"].default: cls for cls in classes}


@lru_cache(maxsize=128)
def get_event_class_for_type(event_type: EventType) -> type | None:
    """Get the event class for a given event type."""
    return _get_event_type_to_class().get(event_type)
