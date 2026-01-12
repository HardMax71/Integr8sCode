from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import ConfigDict, Discriminator, Field, TypeAdapter
from pydantic_avro.to_avro.base import AvroBase

from app.domain.enums.auth import LoginMethod
from app.domain.enums.common import Environment
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.domain.enums.storage import ExecutionErrorType, StorageType
from app.domain.execution import ResourceUsageDomain


class EventMetadata(AvroBase):
    """Event metadata - embedded in all events."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    service_name: str
    service_version: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION


class BaseEvent(AvroBase):
    """Base fields for all domain events."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None
    metadata: EventMetadata


# --- Execution Events ---


class ExecutionRequestedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_REQUESTED] = EventType.EXECUTION_REQUESTED
    execution_id: str
    script: str
    language: str
    language_version: str
    runtime_image: str
    runtime_command: list[str]
    runtime_filename: str
    timeout_seconds: int
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    priority: int = 5


class ExecutionAcceptedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_ACCEPTED] = EventType.EXECUTION_ACCEPTED
    execution_id: str
    queue_position: int
    estimated_wait_seconds: float | None = None
    priority: int = 5


class ExecutionQueuedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_QUEUED] = EventType.EXECUTION_QUEUED
    execution_id: str
    position_in_queue: int | None = None
    estimated_start_time: datetime | None = None


class ExecutionStartedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_STARTED] = EventType.EXECUTION_STARTED
    execution_id: str
    pod_name: str
    node_name: str | None = None
    container_id: str | None = None


class ExecutionRunningEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_RUNNING] = EventType.EXECUTION_RUNNING
    execution_id: str
    pod_name: str
    progress_percentage: int | None = None


class ExecutionCompletedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_COMPLETED] = EventType.EXECUTION_COMPLETED
    execution_id: str
    exit_code: int
    resource_usage: ResourceUsageDomain | None = None
    stdout: str = ""
    stderr: str = ""


class ExecutionFailedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_FAILED] = EventType.EXECUTION_FAILED
    execution_id: str
    exit_code: int
    error_type: ExecutionErrorType | None = None
    error_message: str = ""
    resource_usage: ResourceUsageDomain | None = None
    stdout: str = ""
    stderr: str = ""


class ExecutionTimeoutEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_TIMEOUT] = EventType.EXECUTION_TIMEOUT
    execution_id: str
    timeout_seconds: int
    resource_usage: ResourceUsageDomain | None = None
    stdout: str = ""
    stderr: str = ""


class ExecutionCancelledEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_CANCELLED] = EventType.EXECUTION_CANCELLED
    execution_id: str
    reason: str
    cancelled_by: str | None = None
    force_terminated: bool = False


# --- Pod Events ---


class PodCreatedEvent(BaseEvent):
    event_type: Literal[EventType.POD_CREATED] = EventType.POD_CREATED
    execution_id: str
    pod_name: str
    namespace: str = "default"


class PodScheduledEvent(BaseEvent):
    event_type: Literal[EventType.POD_SCHEDULED] = EventType.POD_SCHEDULED
    execution_id: str
    pod_name: str
    node_name: str = ""


class PodRunningEvent(BaseEvent):
    event_type: Literal[EventType.POD_RUNNING] = EventType.POD_RUNNING
    execution_id: str
    pod_name: str
    container_statuses: str = ""


class PodSucceededEvent(BaseEvent):
    event_type: Literal[EventType.POD_SUCCEEDED] = EventType.POD_SUCCEEDED
    execution_id: str
    pod_name: str
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None


class PodFailedEvent(BaseEvent):
    event_type: Literal[EventType.POD_FAILED] = EventType.POD_FAILED
    execution_id: str
    pod_name: str
    exit_code: int = 1
    reason: str | None = None
    message: str | None = None
    stdout: str | None = None
    stderr: str | None = None


class PodTerminatedEvent(BaseEvent):
    event_type: Literal[EventType.POD_TERMINATED] = EventType.POD_TERMINATED
    execution_id: str
    pod_name: str
    exit_code: int = 0
    reason: str | None = None
    message: str | None = None


class PodDeletedEvent(BaseEvent):
    event_type: Literal[EventType.POD_DELETED] = EventType.POD_DELETED
    execution_id: str
    pod_name: str
    reason: str | None = None


# --- Result Events ---


class ResultStoredEvent(BaseEvent):
    event_type: Literal[EventType.RESULT_STORED] = EventType.RESULT_STORED
    execution_id: str
    storage_type: StorageType | None = None
    storage_path: str = ""
    size_bytes: int = 0


class ResultFailedEvent(BaseEvent):
    event_type: Literal[EventType.RESULT_FAILED] = EventType.RESULT_FAILED
    execution_id: str
    error: str = ""
    storage_type: StorageType | None = None


# --- User Events ---


class UserSettingsUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_SETTINGS_UPDATED] = EventType.USER_SETTINGS_UPDATED
    user_id: str
    changed_fields: list[str] = Field(default_factory=list)
    reason: str | None = None


class UserRegisteredEvent(BaseEvent):
    event_type: Literal[EventType.USER_REGISTERED] = EventType.USER_REGISTERED
    user_id: str
    username: str
    email: str


class UserLoginEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGIN] = EventType.USER_LOGIN
    user_id: str
    login_method: LoginMethod
    ip_address: str | None = None
    user_agent: str | None = None


class UserLoggedInEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGGED_IN] = EventType.USER_LOGGED_IN
    user_id: str
    login_method: LoginMethod
    ip_address: str | None = None
    user_agent: str | None = None


class UserLoggedOutEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGGED_OUT] = EventType.USER_LOGGED_OUT
    user_id: str
    logout_reason: str | None = None


class UserUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_UPDATED] = EventType.USER_UPDATED
    user_id: str
    updated_fields: list[str] = Field(default_factory=list)
    updated_by: str | None = None


class UserDeletedEvent(BaseEvent):
    event_type: Literal[EventType.USER_DELETED] = EventType.USER_DELETED
    user_id: str
    deleted_by: str | None = None
    reason: str | None = None


# --- Notification Events ---


class NotificationCreatedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_CREATED] = EventType.NOTIFICATION_CREATED
    notification_id: str
    user_id: str
    subject: str
    body: str
    severity: NotificationSeverity
    tags: list[str] = Field(default_factory=list)
    channels: list[NotificationChannel] = Field(default_factory=list)


class NotificationSentEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_SENT] = EventType.NOTIFICATION_SENT
    notification_id: str
    user_id: str
    channel: NotificationChannel
    sent_at: datetime


class NotificationDeliveredEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_DELIVERED] = EventType.NOTIFICATION_DELIVERED
    notification_id: str
    user_id: str
    channel: NotificationChannel
    delivered_at: datetime


class NotificationFailedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_FAILED] = EventType.NOTIFICATION_FAILED
    notification_id: str
    user_id: str
    channel: NotificationChannel
    error: str
    retry_count: int = 0


class NotificationReadEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_READ] = EventType.NOTIFICATION_READ
    notification_id: str
    user_id: str
    read_at: datetime


class NotificationClickedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_CLICKED] = EventType.NOTIFICATION_CLICKED
    notification_id: str
    user_id: str
    clicked_at: datetime
    action: str | None = None


class NotificationPreferencesUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_PREFERENCES_UPDATED] = EventType.NOTIFICATION_PREFERENCES_UPDATED
    user_id: str
    changed_fields: list[str] = Field(default_factory=list)


# --- Saga Events ---


class SagaStartedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_STARTED] = EventType.SAGA_STARTED
    saga_id: str
    saga_name: str
    execution_id: str
    initial_event_id: str


class SagaCompletedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_COMPLETED] = EventType.SAGA_COMPLETED
    saga_id: str
    saga_name: str
    execution_id: str
    completed_steps: list[str] = Field(default_factory=list)


class SagaFailedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_FAILED] = EventType.SAGA_FAILED
    saga_id: str
    saga_name: str
    execution_id: str
    failed_step: str
    error: str


class SagaCancelledEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_CANCELLED] = EventType.SAGA_CANCELLED
    saga_id: str
    saga_name: str
    execution_id: str
    reason: str
    completed_steps: list[str] = Field(default_factory=list)
    compensated_steps: list[str] = Field(default_factory=list)
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None


class SagaCompensatingEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_COMPENSATING] = EventType.SAGA_COMPENSATING
    saga_id: str
    saga_name: str
    execution_id: str
    compensating_step: str


class SagaCompensatedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_COMPENSATED] = EventType.SAGA_COMPENSATED
    saga_id: str
    saga_name: str
    execution_id: str
    compensated_steps: list[str] = Field(default_factory=list)


# --- Saga Command Events ---


class CreatePodCommandEvent(BaseEvent):
    event_type: Literal[EventType.CREATE_POD_COMMAND] = EventType.CREATE_POD_COMMAND
    saga_id: str
    execution_id: str
    script: str
    language: str
    language_version: str
    runtime_image: str
    runtime_command: list[str] = Field(default_factory=list)
    runtime_filename: str
    timeout_seconds: int
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    priority: int = 5


class DeletePodCommandEvent(BaseEvent):
    event_type: Literal[EventType.DELETE_POD_COMMAND] = EventType.DELETE_POD_COMMAND
    saga_id: str
    execution_id: str
    reason: str
    pod_name: str | None = None
    namespace: str | None = None


class AllocateResourcesCommandEvent(BaseEvent):
    event_type: Literal[EventType.ALLOCATE_RESOURCES_COMMAND] = EventType.ALLOCATE_RESOURCES_COMMAND
    execution_id: str
    cpu_request: str
    memory_request: str


class ReleaseResourcesCommandEvent(BaseEvent):
    event_type: Literal[EventType.RELEASE_RESOURCES_COMMAND] = EventType.RELEASE_RESOURCES_COMMAND
    execution_id: str
    cpu_request: str
    memory_request: str


# --- Script Events ---


class ScriptSavedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_SAVED] = EventType.SCRIPT_SAVED
    script_id: str
    user_id: str
    title: str
    language: str


class ScriptDeletedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_DELETED] = EventType.SCRIPT_DELETED
    script_id: str
    user_id: str
    deleted_by: str | None = None


class ScriptSharedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_SHARED] = EventType.SCRIPT_SHARED
    script_id: str
    shared_by: str
    shared_with: list[str] = Field(default_factory=list)
    permissions: str


# --- Security Events ---


class SecurityViolationEvent(BaseEvent):
    event_type: Literal[EventType.SECURITY_VIOLATION] = EventType.SECURITY_VIOLATION
    user_id: str | None = None
    violation_type: str
    details: str
    ip_address: str | None = None


class RateLimitExceededEvent(BaseEvent):
    event_type: Literal[EventType.RATE_LIMIT_EXCEEDED] = EventType.RATE_LIMIT_EXCEEDED
    user_id: str | None = None
    endpoint: str
    limit: int
    window_seconds: int


class AuthFailedEvent(BaseEvent):
    event_type: Literal[EventType.AUTH_FAILED] = EventType.AUTH_FAILED
    username: str | None = None
    reason: str
    ip_address: str | None = None


# --- Resource Events ---


class ResourceLimitExceededEvent(BaseEvent):
    event_type: Literal[EventType.RESOURCE_LIMIT_EXCEEDED] = EventType.RESOURCE_LIMIT_EXCEEDED
    resource_type: str
    limit: int
    requested: int
    user_id: str | None = None


class QuotaExceededEvent(BaseEvent):
    event_type: Literal[EventType.QUOTA_EXCEEDED] = EventType.QUOTA_EXCEEDED
    quota_type: str
    limit: int
    current_usage: int
    user_id: str


# --- System Events ---


class SystemErrorEvent(BaseEvent):
    event_type: Literal[EventType.SYSTEM_ERROR] = EventType.SYSTEM_ERROR
    error_type: str
    message: str
    service_name: str
    stack_trace: str | None = None


class ServiceUnhealthyEvent(BaseEvent):
    event_type: Literal[EventType.SERVICE_UNHEALTHY] = EventType.SERVICE_UNHEALTHY
    service_name: str
    health_check: str
    reason: str


class ServiceRecoveredEvent(BaseEvent):
    event_type: Literal[EventType.SERVICE_RECOVERED] = EventType.SERVICE_RECOVERED
    service_name: str
    health_check: str
    downtime_seconds: int


# --- DLQ Events ---


class DLQMessageReceivedEvent(BaseEvent):
    """Emitted when a message is received and persisted in the DLQ."""

    event_type: Literal[EventType.DLQ_MESSAGE_RECEIVED] = EventType.DLQ_MESSAGE_RECEIVED
    dlq_event_id: str  # The event_id of the failed message
    original_topic: str
    original_event_type: str
    error: str
    retry_count: int
    producer_id: str
    failed_at: datetime


class DLQMessageRetriedEvent(BaseEvent):
    """Emitted when a DLQ message is retried."""

    event_type: Literal[EventType.DLQ_MESSAGE_RETRIED] = EventType.DLQ_MESSAGE_RETRIED
    dlq_event_id: str  # The event_id of the retried message
    original_topic: str
    original_event_type: str
    retry_count: int  # New retry count after this retry
    retry_topic: str  # Topic the message was retried to


class DLQMessageDiscardedEvent(BaseEvent):
    """Emitted when a DLQ message is discarded (max retries exceeded or manual discard)."""

    event_type: Literal[EventType.DLQ_MESSAGE_DISCARDED] = EventType.DLQ_MESSAGE_DISCARDED
    dlq_event_id: str  # The event_id of the discarded message
    original_topic: str
    original_event_type: str
    reason: str
    retry_count: int  # Final retry count when discarded


# --- Archived Event (for deleted events) ---


class ArchivedEvent(AvroBase):
    """Archived event with deletion metadata. Wraps the original event data."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadata
    stored_at: datetime | None = None
    ttl_expires_at: datetime | None = None
    # Archive-specific fields
    deleted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_by: str | None = None
    deletion_reason: str | None = None


# --- Discriminated Union: TYPE SYSTEM handles dispatch ---

DomainEvent = Annotated[
    # Execution Events
    ExecutionRequestedEvent
    | ExecutionAcceptedEvent
    | ExecutionQueuedEvent
    | ExecutionStartedEvent
    | ExecutionRunningEvent
    | ExecutionCompletedEvent
    | ExecutionFailedEvent
    | ExecutionTimeoutEvent
    | ExecutionCancelledEvent
    # Pod Events
    | PodCreatedEvent
    | PodScheduledEvent
    | PodRunningEvent
    | PodSucceededEvent
    | PodFailedEvent
    | PodTerminatedEvent
    | PodDeletedEvent
    # Result Events
    | ResultStoredEvent
    | ResultFailedEvent
    # User Events
    | UserSettingsUpdatedEvent
    | UserRegisteredEvent
    | UserLoginEvent
    | UserLoggedInEvent
    | UserLoggedOutEvent
    | UserUpdatedEvent
    | UserDeletedEvent
    # Notification Events
    | NotificationCreatedEvent
    | NotificationSentEvent
    | NotificationDeliveredEvent
    | NotificationFailedEvent
    | NotificationReadEvent
    | NotificationClickedEvent
    | NotificationPreferencesUpdatedEvent
    # Saga Events
    | SagaStartedEvent
    | SagaCompletedEvent
    | SagaFailedEvent
    | SagaCancelledEvent
    | SagaCompensatingEvent
    | SagaCompensatedEvent
    # Saga Command Events
    | CreatePodCommandEvent
    | DeletePodCommandEvent
    | AllocateResourcesCommandEvent
    | ReleaseResourcesCommandEvent
    # Script Events
    | ScriptSavedEvent
    | ScriptDeletedEvent
    | ScriptSharedEvent
    # Security Events
    | SecurityViolationEvent
    | RateLimitExceededEvent
    | AuthFailedEvent
    # Resource Events
    | ResourceLimitExceededEvent
    | QuotaExceededEvent
    # System Events
    | SystemErrorEvent
    | ServiceUnhealthyEvent
    | ServiceRecoveredEvent
    # DLQ Events
    | DLQMessageReceivedEvent
    | DLQMessageRetriedEvent
    | DLQMessageDiscardedEvent,
    Discriminator("event_type"),
]

# TypeAdapter for polymorphic loading - validates raw data to correct typed event
domain_event_adapter: TypeAdapter[DomainEvent] = TypeAdapter(DomainEvent)
