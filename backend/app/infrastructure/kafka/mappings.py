from functools import lru_cache
from typing import get_args, get_origin

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic

# EventType -> KafkaTopic routing
EVENT_TYPE_TO_TOPIC: dict[EventType, KafkaTopic] = {
    # Execution events
    EventType.EXECUTION_REQUESTED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_ACCEPTED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_QUEUED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_STARTED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_RUNNING: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_COMPLETED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_FAILED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_TIMEOUT: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_CANCELLED: KafkaTopic.EXECUTION_EVENTS,
    # Pod events
    EventType.POD_CREATED: KafkaTopic.POD_EVENTS,
    EventType.POD_SCHEDULED: KafkaTopic.POD_EVENTS,
    EventType.POD_RUNNING: KafkaTopic.POD_EVENTS,
    EventType.POD_SUCCEEDED: KafkaTopic.POD_EVENTS,
    EventType.POD_FAILED: KafkaTopic.POD_EVENTS,
    EventType.POD_TERMINATED: KafkaTopic.POD_EVENTS,
    EventType.POD_DELETED: KafkaTopic.POD_EVENTS,
    # Result events
    EventType.RESULT_STORED: KafkaTopic.EXECUTION_RESULTS,
    EventType.RESULT_FAILED: KafkaTopic.EXECUTION_RESULTS,
    # User events
    EventType.USER_REGISTERED: KafkaTopic.USER_EVENTS,
    EventType.USER_LOGIN: KafkaTopic.USER_EVENTS,
    EventType.USER_LOGGED_IN: KafkaTopic.USER_EVENTS,
    EventType.USER_LOGGED_OUT: KafkaTopic.USER_EVENTS,
    EventType.USER_UPDATED: KafkaTopic.USER_EVENTS,
    EventType.USER_DELETED: KafkaTopic.USER_EVENTS,
    EventType.USER_SETTINGS_UPDATED: KafkaTopic.USER_SETTINGS_EVENTS,
    # Notification events
    EventType.NOTIFICATION_CREATED: KafkaTopic.NOTIFICATION_EVENTS,
    EventType.NOTIFICATION_SENT: KafkaTopic.NOTIFICATION_EVENTS,
    EventType.NOTIFICATION_DELIVERED: KafkaTopic.NOTIFICATION_EVENTS,
    EventType.NOTIFICATION_FAILED: KafkaTopic.NOTIFICATION_EVENTS,
    EventType.NOTIFICATION_READ: KafkaTopic.NOTIFICATION_EVENTS,
    EventType.NOTIFICATION_CLICKED: KafkaTopic.NOTIFICATION_EVENTS,
    EventType.NOTIFICATION_PREFERENCES_UPDATED: KafkaTopic.NOTIFICATION_EVENTS,
    # Script events
    EventType.SCRIPT_SAVED: KafkaTopic.SCRIPT_EVENTS,
    EventType.SCRIPT_DELETED: KafkaTopic.SCRIPT_EVENTS,
    EventType.SCRIPT_SHARED: KafkaTopic.SCRIPT_EVENTS,
    # Security events
    EventType.SECURITY_VIOLATION: KafkaTopic.SECURITY_EVENTS,
    EventType.RATE_LIMIT_EXCEEDED: KafkaTopic.SECURITY_EVENTS,
    EventType.AUTH_FAILED: KafkaTopic.SECURITY_EVENTS,
    # Resource events
    EventType.RESOURCE_LIMIT_EXCEEDED: KafkaTopic.RESOURCE_EVENTS,
    EventType.QUOTA_EXCEEDED: KafkaTopic.RESOURCE_EVENTS,
    # System events
    EventType.SYSTEM_ERROR: KafkaTopic.SYSTEM_EVENTS,
    EventType.SERVICE_UNHEALTHY: KafkaTopic.SYSTEM_EVENTS,
    EventType.SERVICE_RECOVERED: KafkaTopic.SYSTEM_EVENTS,
    # Saga events
    EventType.SAGA_STARTED: KafkaTopic.SAGA_EVENTS,
    EventType.SAGA_COMPLETED: KafkaTopic.SAGA_EVENTS,
    EventType.SAGA_FAILED: KafkaTopic.SAGA_EVENTS,
    EventType.SAGA_CANCELLED: KafkaTopic.SAGA_EVENTS,
    EventType.SAGA_COMPENSATING: KafkaTopic.SAGA_EVENTS,
    EventType.SAGA_COMPENSATED: KafkaTopic.SAGA_EVENTS,
    # Saga command events
    EventType.CREATE_POD_COMMAND: KafkaTopic.SAGA_COMMANDS,
    EventType.DELETE_POD_COMMAND: KafkaTopic.SAGA_COMMANDS,
    EventType.ALLOCATE_RESOURCES_COMMAND: KafkaTopic.SAGA_COMMANDS,
    EventType.RELEASE_RESOURCES_COMMAND: KafkaTopic.SAGA_COMMANDS,
    # DLQ events
    EventType.DLQ_MESSAGE_RECEIVED: KafkaTopic.DLQ_EVENTS,
    EventType.DLQ_MESSAGE_RETRIED: KafkaTopic.DLQ_EVENTS,
    EventType.DLQ_MESSAGE_DISCARDED: KafkaTopic.DLQ_EVENTS,
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


@lru_cache(maxsize=128)
def get_topic_for_event(event_type: EventType) -> KafkaTopic:
    """Get the Kafka topic for a given event type."""
    return EVENT_TYPE_TO_TOPIC.get(event_type, KafkaTopic.SYSTEM_EVENTS)


def get_event_types_for_topic(topic: KafkaTopic) -> list[EventType]:
    """Get all event types that publish to a given topic."""
    return [et for et, t in EVENT_TYPE_TO_TOPIC.items() if t == topic]
