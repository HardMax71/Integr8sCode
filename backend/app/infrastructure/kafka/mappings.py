from functools import lru_cache
from typing import Type

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionQueuedEvent,
    ExecutionRequestedEvent,
    ExecutionRunningEvent,
    ExecutionStartedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.notification import (
    NotificationClickedEvent,
    NotificationCreatedEvent,
    NotificationDeliveredEvent,
    NotificationFailedEvent,
    NotificationReadEvent,
    NotificationSentEvent,
)
from app.infrastructure.kafka.events.pod import (
    PodCreatedEvent,
    PodDeletedEvent,
    PodFailedEvent,
    PodRunningEvent,
    PodScheduledEvent,
    PodSucceededEvent,
    PodTerminatedEvent,
)
from app.infrastructure.kafka.events.saga import (
    AllocateResourcesCommandEvent,
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    ReleaseResourcesCommandEvent,
    SagaCancelledEvent,
    SagaCompensatedEvent,
    SagaCompensatingEvent,
    SagaCompletedEvent,
    SagaFailedEvent,
    SagaStartedEvent,
)
from app.infrastructure.kafka.events.system import (
    AuthFailedEvent,
    QuotaExceededEvent,
    RateLimitExceededEvent,
    ResourceLimitExceededEvent,
    ResultFailedEvent,
    ResultStoredEvent,
    ScriptDeletedEvent,
    ScriptSavedEvent,
    ScriptSharedEvent,
    SecurityViolationEvent,
    ServiceRecoveredEvent,
    ServiceUnhealthyEvent,
    SystemErrorEvent,
)
from app.infrastructure.kafka.events.user import (
    UserDeletedEvent,
    UserEditorSettingsUpdatedEvent,
    UserLoggedInEvent,
    UserLoggedOutEvent,
    UserNotificationSettingsUpdatedEvent,
    UserRegisteredEvent,
    UserSettingsUpdatedEvent,
    UserThemeChangedEvent,
    UserUpdatedEvent,
)


@lru_cache(maxsize=128)
def get_event_class_for_type(event_type: EventType) -> Type[BaseEvent] | None:
    """Get the event class for a given event type."""
    event_map: dict[EventType, Type[BaseEvent]] = {
        # Execution events
        EventType.EXECUTION_REQUESTED: ExecutionRequestedEvent,
        EventType.EXECUTION_QUEUED: ExecutionQueuedEvent,
        EventType.EXECUTION_STARTED: ExecutionStartedEvent,
        EventType.EXECUTION_RUNNING: ExecutionRunningEvent,
        EventType.EXECUTION_COMPLETED: ExecutionCompletedEvent,
        EventType.EXECUTION_FAILED: ExecutionFailedEvent,
        EventType.EXECUTION_TIMEOUT: ExecutionTimeoutEvent,
        EventType.EXECUTION_CANCELLED: ExecutionCancelledEvent,
        
        # Pod events
        EventType.POD_CREATED: PodCreatedEvent,
        EventType.POD_SCHEDULED: PodScheduledEvent,
        EventType.POD_RUNNING: PodRunningEvent,
        EventType.POD_SUCCEEDED: PodSucceededEvent,
        EventType.POD_FAILED: PodFailedEvent,
        EventType.POD_TERMINATED: PodTerminatedEvent,
        EventType.POD_DELETED: PodDeletedEvent,
        
        # User events
        EventType.USER_REGISTERED: UserRegisteredEvent,
        EventType.USER_LOGGED_IN: UserLoggedInEvent,
        EventType.USER_LOGGED_OUT: UserLoggedOutEvent,
        EventType.USER_UPDATED: UserUpdatedEvent,
        EventType.USER_DELETED: UserDeletedEvent,
        EventType.USER_SETTINGS_UPDATED: UserSettingsUpdatedEvent,
        EventType.USER_THEME_CHANGED: UserThemeChangedEvent,
        EventType.USER_NOTIFICATION_SETTINGS_UPDATED: UserNotificationSettingsUpdatedEvent,
        EventType.USER_EDITOR_SETTINGS_UPDATED: UserEditorSettingsUpdatedEvent,
        
        # Notification events
        EventType.NOTIFICATION_CREATED: NotificationCreatedEvent,
        EventType.NOTIFICATION_SENT: NotificationSentEvent,
        EventType.NOTIFICATION_DELIVERED: NotificationDeliveredEvent,
        EventType.NOTIFICATION_FAILED: NotificationFailedEvent,
        EventType.NOTIFICATION_READ: NotificationReadEvent,
        EventType.NOTIFICATION_CLICKED: NotificationClickedEvent,
        
        # Script events
        EventType.SCRIPT_SAVED: ScriptSavedEvent,
        EventType.SCRIPT_DELETED: ScriptDeletedEvent,
        EventType.SCRIPT_SHARED: ScriptSharedEvent,
        
        # Security events
        EventType.SECURITY_VIOLATION: SecurityViolationEvent,
        EventType.RATE_LIMIT_EXCEEDED: RateLimitExceededEvent,
        EventType.AUTH_FAILED: AuthFailedEvent,
        
        # Resource events
        EventType.RESOURCE_LIMIT_EXCEEDED: ResourceLimitExceededEvent,
        EventType.QUOTA_EXCEEDED: QuotaExceededEvent,
        
        # System events
        EventType.SYSTEM_ERROR: SystemErrorEvent,
        EventType.SERVICE_UNHEALTHY: ServiceUnhealthyEvent,
        EventType.SERVICE_RECOVERED: ServiceRecoveredEvent,
        
        # Result events
        EventType.RESULT_STORED: ResultStoredEvent,
        EventType.RESULT_FAILED: ResultFailedEvent,
        
        # Saga events
        EventType.SAGA_STARTED: SagaStartedEvent,
        EventType.SAGA_COMPLETED: SagaCompletedEvent,
        EventType.SAGA_FAILED: SagaFailedEvent,
        EventType.SAGA_CANCELLED: SagaCancelledEvent,
        EventType.SAGA_COMPENSATING: SagaCompensatingEvent,
        EventType.SAGA_COMPENSATED: SagaCompensatedEvent,
        
        # Saga command events
        EventType.CREATE_POD_COMMAND: CreatePodCommandEvent,
        EventType.DELETE_POD_COMMAND: DeletePodCommandEvent,
        EventType.ALLOCATE_RESOURCES_COMMAND: AllocateResourcesCommandEvent,
        EventType.RELEASE_RESOURCES_COMMAND: ReleaseResourcesCommandEvent,
    }
    
    return event_map.get(event_type)


@lru_cache(maxsize=128)
def get_topic_for_event(event_type: EventType) -> KafkaTopic:
    """Get the Kafka topic for a given event type."""
    event_class = get_event_class_for_type(event_type)
    if event_class:
        return event_class.topic
    
    # Default fallback
    return KafkaTopic.SYSTEM_EVENTS


def get_event_types_for_topic(topic: KafkaTopic) -> list[EventType]:
    """Get all event types that publish to a given topic."""
    event_types = []
    for event_type in EventType:
        if get_topic_for_event(event_type) == topic:
            event_types.append(event_type)
    return event_types
