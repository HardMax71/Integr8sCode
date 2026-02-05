import re
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.auth import LoginMethod
from app.domain.enums.common import Environment
from app.domain.enums.execution import QueuePriority
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.domain.enums.storage import ExecutionErrorType, StorageType


def _to_snake_case(name: str) -> str:
    """Convert class name to snake_case topic name.

    ExecutionRequestedEvent -> execution_requested
    PodCreatedEvent -> pod_created
    """
    if name.endswith("Event"):
        name = name[:-5]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class ResourceUsageDomain(BaseModel):
    """Resource usage metrics from script execution."""

    model_config = ConfigDict(from_attributes=True)

    execution_time_wall_seconds: float = 0.0
    cpu_time_jiffies: int = 0
    clk_tck_hertz: int = 0
    peak_memory_kb: int = 0


class EventMetadata(BaseModel):
    """Event metadata - embedded in all events."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    service_name: str
    service_version: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION


class BaseEvent(BaseModel):
    """Base fields for all domain events.

    Topic routing: Each event class maps to its own Kafka topic.
    Topic name is derived from class name: ExecutionRequestedEvent -> execution_requested
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"required": ["event_id", "event_version", "timestamp", "metadata"]},
    )

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None
    metadata: EventMetadata

    @classmethod
    def topic(cls, prefix: str = "") -> str:
        """Get Kafka topic name for this event class."""
        return f"{prefix}{_to_snake_case(cls.__name__)}"


# --- Execution Events ---


class ExecutionRequestedEvent(BaseEvent):
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
    priority: QueuePriority = QueuePriority.NORMAL


class ExecutionAcceptedEvent(BaseEvent):
    execution_id: str
    queue_position: int
    estimated_wait_seconds: float | None = None
    priority: QueuePriority = QueuePriority.NORMAL


class ExecutionQueuedEvent(BaseEvent):
    execution_id: str
    position_in_queue: int | None = None
    estimated_start_time: datetime | None = None


class ExecutionStartedEvent(BaseEvent):
    execution_id: str
    pod_name: str
    node_name: str | None = None
    container_id: str | None = None


class ExecutionRunningEvent(BaseEvent):
    execution_id: str
    pod_name: str
    progress_percentage: int | None = None


class ExecutionCompletedEvent(BaseEvent):
    execution_id: str
    exit_code: int
    resource_usage: ResourceUsageDomain | None = None
    stdout: str = ""
    stderr: str = ""


class ExecutionFailedEvent(BaseEvent):
    execution_id: str
    exit_code: int
    error_type: ExecutionErrorType
    error_message: str = ""
    resource_usage: ResourceUsageDomain | None = None
    stdout: str = ""
    stderr: str = ""


class ExecutionTimeoutEvent(BaseEvent):
    execution_id: str
    timeout_seconds: int
    resource_usage: ResourceUsageDomain | None = None
    stdout: str = ""
    stderr: str = ""


class ExecutionCancelledEvent(BaseEvent):
    execution_id: str
    reason: str
    cancelled_by: str | None = None
    force_terminated: bool = False


# --- Pod Events ---


class PodCreatedEvent(BaseEvent):
    execution_id: str
    pod_name: str
    namespace: str = "default"


class PodScheduledEvent(BaseEvent):
    execution_id: str
    pod_name: str
    node_name: str = ""


class ContainerStatusInfo(BaseModel):
    """Container status information from Kubernetes pod."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    ready: bool = False
    restart_count: int = 0
    state: str = "unknown"


class PodRunningEvent(BaseEvent):
    execution_id: str
    pod_name: str
    container_statuses: list[ContainerStatusInfo] = Field(default_factory=list)


class PodSucceededEvent(BaseEvent):
    execution_id: str
    pod_name: str
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None


class PodFailedEvent(BaseEvent):
    execution_id: str
    pod_name: str
    exit_code: int = 1
    reason: str | None = None
    message: str | None = None
    stdout: str | None = None
    stderr: str | None = None


class PodTerminatedEvent(BaseEvent):
    execution_id: str
    pod_name: str
    exit_code: int = 0
    reason: str | None = None
    message: str | None = None


class PodDeletedEvent(BaseEvent):
    execution_id: str
    pod_name: str
    reason: str | None = None


# --- Result Events ---


class ResultStoredEvent(BaseEvent):
    execution_id: str
    storage_type: StorageType | None = None
    storage_path: str = ""
    size_bytes: int = 0


class ResultFailedEvent(BaseEvent):
    execution_id: str
    error: str = ""
    storage_type: StorageType | None = None


# --- User Events ---


class UserSettingsUpdatedEvent(BaseEvent):
    model_config = ConfigDict(extra="allow")

    user_id: str
    changed_fields: list[str] = Field(default_factory=list)
    reason: str | None = None


class UserRegisteredEvent(BaseEvent):
    user_id: str
    username: str
    email: str


class UserLoginEvent(BaseEvent):
    user_id: str
    login_method: LoginMethod
    ip_address: str | None = None
    user_agent: str | None = None


class UserLoggedInEvent(BaseEvent):
    user_id: str
    login_method: LoginMethod
    ip_address: str | None = None
    user_agent: str | None = None


class UserLoggedOutEvent(BaseEvent):
    user_id: str
    logout_reason: str | None = None


class UserUpdatedEvent(BaseEvent):
    user_id: str
    updated_fields: list[str] = Field(default_factory=list)
    updated_by: str | None = None


class UserDeletedEvent(BaseEvent):
    user_id: str
    deleted_by: str | None = None
    reason: str | None = None


# --- Notification Events ---


class NotificationCreatedEvent(BaseEvent):
    notification_id: str
    user_id: str
    subject: str
    body: str
    severity: NotificationSeverity
    tags: list[str] = Field(default_factory=list)
    channels: list[NotificationChannel] = Field(default_factory=list)


class NotificationSentEvent(BaseEvent):
    notification_id: str
    user_id: str
    channel: NotificationChannel
    sent_at: datetime


class NotificationDeliveredEvent(BaseEvent):
    notification_id: str
    user_id: str
    channel: NotificationChannel
    delivered_at: datetime


class NotificationFailedEvent(BaseEvent):
    notification_id: str
    user_id: str
    channel: NotificationChannel
    error: str
    retry_count: int = 0


class NotificationReadEvent(BaseEvent):
    notification_id: str
    user_id: str
    read_at: datetime


class NotificationAllReadEvent(BaseEvent):
    user_id: str
    count: int
    read_at: datetime


class NotificationClickedEvent(BaseEvent):
    notification_id: str
    user_id: str
    clicked_at: datetime
    action: str | None = None


class NotificationPreferencesUpdatedEvent(BaseEvent):
    user_id: str
    changed_fields: list[str] = Field(default_factory=list)


# --- Saga Events ---


class SagaStartedEvent(BaseEvent):
    saga_id: str
    saga_name: str
    execution_id: str
    initial_event_id: str


class SagaCompletedEvent(BaseEvent):
    saga_id: str
    saga_name: str
    execution_id: str
    completed_steps: list[str] = Field(default_factory=list)


class SagaFailedEvent(BaseEvent):
    saga_id: str
    saga_name: str
    execution_id: str
    failed_step: str
    error: str


class SagaCancelledEvent(BaseEvent):
    saga_id: str
    saga_name: str
    execution_id: str
    reason: str
    completed_steps: list[str] = Field(default_factory=list)
    compensated_steps: list[str] = Field(default_factory=list)
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None


class SagaCompensatingEvent(BaseEvent):
    saga_id: str
    saga_name: str
    execution_id: str
    compensating_step: str


class SagaCompensatedEvent(BaseEvent):
    saga_id: str
    saga_name: str
    execution_id: str
    compensated_steps: list[str] = Field(default_factory=list)


# --- Saga Command Events ---


class CreatePodCommandEvent(BaseEvent):
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
    priority: QueuePriority = QueuePriority.NORMAL


class DeletePodCommandEvent(BaseEvent):
    saga_id: str
    execution_id: str
    reason: str
    pod_name: str | None = None
    namespace: str | None = None


class AllocateResourcesCommandEvent(BaseEvent):
    execution_id: str
    cpu_request: str
    memory_request: str


class ReleaseResourcesCommandEvent(BaseEvent):
    execution_id: str
    cpu_request: str
    memory_request: str


# --- Script Events ---


class ScriptSavedEvent(BaseEvent):
    script_id: str
    user_id: str
    title: str
    language: str


class ScriptDeletedEvent(BaseEvent):
    script_id: str
    user_id: str
    deleted_by: str | None = None


class ScriptSharedEvent(BaseEvent):
    script_id: str
    shared_by: str
    shared_with: list[str] = Field(default_factory=list)
    permissions: str


# --- Security Events ---


class SecurityViolationEvent(BaseEvent):
    user_id: str | None = None
    violation_type: str
    details: str
    ip_address: str | None = None


class RateLimitExceededEvent(BaseEvent):
    user_id: str | None = None
    endpoint: str
    limit: int
    window_seconds: int


class AuthFailedEvent(BaseEvent):
    username: str | None = None
    reason: str
    ip_address: str | None = None


# --- Resource Events ---


class ResourceLimitExceededEvent(BaseEvent):
    resource_type: str
    limit: int
    requested: int
    user_id: str | None = None


class QuotaExceededEvent(BaseEvent):
    quota_type: str
    limit: int
    current_usage: int
    user_id: str


# --- System Events ---


class SystemErrorEvent(BaseEvent):
    error_type: str
    message: str
    service_name: str
    stack_trace: str | None = None


class ServiceUnhealthyEvent(BaseEvent):
    service_name: str
    health_check: str
    reason: str


class ServiceRecoveredEvent(BaseEvent):
    service_name: str
    health_check: str
    downtime_seconds: int


# --- DLQ Events ---


class DLQMessageReceivedEvent(BaseEvent):
    """Emitted when a message is received and persisted in the DLQ."""

    dlq_event_id: str
    original_topic: str
    error: str
    retry_count: int
    producer_id: str
    failed_at: datetime


class DLQMessageRetriedEvent(BaseEvent):
    """Emitted when a DLQ message is retried."""

    dlq_event_id: str
    original_topic: str
    retry_count: int
    retry_topic: str


class DLQMessageDiscardedEvent(BaseEvent):
    """Emitted when a DLQ message is discarded (max retries exceeded or manual discard)."""

    dlq_event_id: str
    original_topic: str
    reason: str
    retry_count: int


# --- Archived Event (for deleted events) ---


class ArchivedEvent(BaseModel):
    """Archived event with deletion metadata. Wraps the original event data."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    topic: str
    event_version: str = "1.0"
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadata
    stored_at: datetime | None = None
    ttl_expires_at: datetime | None = None
    deleted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_by: str | None = None
    deletion_reason: str | None = None
