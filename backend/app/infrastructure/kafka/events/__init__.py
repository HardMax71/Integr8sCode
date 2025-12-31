from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionAcceptedEvent,
    ExecutionCancelledEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionQueuedEvent,
    ExecutionRequestedEvent,
    ExecutionRunningEvent,
    ExecutionStartedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
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
    UserLoggedInEvent,
    UserLoggedOutEvent,
    UserRegisteredEvent,
    UserSettingsUpdatedEvent,
    UserUpdatedEvent,
)

__all__ = [
    # Base
    "BaseEvent",
    "AvroEventMetadata",
    # Execution
    "ExecutionRequestedEvent",
    "ExecutionAcceptedEvent",
    "ExecutionQueuedEvent",
    "ExecutionRunningEvent",
    "ExecutionStartedEvent",
    "ExecutionCompletedEvent",
    "ExecutionFailedEvent",
    "ExecutionTimeoutEvent",
    "ExecutionCancelledEvent",
    # Pod
    "PodCreatedEvent",
    "PodScheduledEvent",
    "PodRunningEvent",
    "PodTerminatedEvent",
    "PodSucceededEvent",
    "PodFailedEvent",
    "PodDeletedEvent",
    # User
    "UserRegisteredEvent",
    "UserLoggedInEvent",
    "UserLoggedOutEvent",
    "UserUpdatedEvent",
    "UserDeletedEvent",
    "UserSettingsUpdatedEvent",
    # Notification
    "NotificationCreatedEvent",
    "NotificationSentEvent",
    "NotificationDeliveredEvent",
    "NotificationFailedEvent",
    "NotificationReadEvent",
    "NotificationClickedEvent",
    # Script
    "ScriptSavedEvent",
    "ScriptDeletedEvent",
    "ScriptSharedEvent",
    # Security
    "SecurityViolationEvent",
    "RateLimitExceededEvent",
    "AuthFailedEvent",
    # Resource
    "ResourceLimitExceededEvent",
    "QuotaExceededEvent",
    # System
    "SystemErrorEvent",
    "ServiceUnhealthyEvent",
    "ServiceRecoveredEvent",
    # Result
    "ResultStoredEvent",
    "ResultFailedEvent",
    # Saga
    "SagaStartedEvent",
    "SagaCompletedEvent",
    "SagaFailedEvent",
    "SagaCancelledEvent",
    "SagaCompensatingEvent",
    "SagaCompensatedEvent",
    # Saga Commands
    "CreatePodCommandEvent",
    "DeletePodCommandEvent",
    "AllocateResourcesCommandEvent",
    "ReleaseResourcesCommandEvent",
]
