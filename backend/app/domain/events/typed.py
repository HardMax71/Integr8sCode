from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Discriminator, Field, TypeAdapter

from app.domain.enums.common import Environment
from app.domain.enums.events import EventType
from app.domain.enums.storage import ExecutionErrorType, StorageType
from app.domain.execution import ResourceUsageDomain


class EventMetadata(BaseModel):
    """Event metadata - embedded in all events."""

    model_config = ConfigDict(from_attributes=True)

    service_name: str
    service_version: str
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION


class BaseEvent(BaseModel):
    """Base fields for all domain events."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None
    metadata: EventMetadata | None = None
    stored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30))


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


# --- Archived Event (for deleted events) ---


class ArchivedEvent(BaseModel):
    """Archived event with deletion metadata. Wraps the original event data."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadata | None = None
    stored_at: datetime | None = None
    ttl_expires_at: datetime | None = None
    # Archive-specific fields
    deleted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_by: str | None = None
    deletion_reason: str | None = None


# --- Discriminated Union: TYPE SYSTEM handles dispatch ---

DomainEvent = Annotated[
    ExecutionRequestedEvent
    | ExecutionAcceptedEvent
    | ExecutionQueuedEvent
    | ExecutionStartedEvent
    | ExecutionRunningEvent
    | ExecutionCompletedEvent
    | ExecutionFailedEvent
    | ExecutionTimeoutEvent
    | ExecutionCancelledEvent
    | PodCreatedEvent
    | PodScheduledEvent
    | PodRunningEvent
    | PodSucceededEvent
    | PodFailedEvent
    | PodTerminatedEvent
    | PodDeletedEvent
    | ResultStoredEvent
    | ResultFailedEvent
    | UserSettingsUpdatedEvent,
    Discriminator("event_type"),
]

# TypeAdapter for polymorphic loading - validates raw data to correct typed event
domain_event_adapter: TypeAdapter[DomainEvent] = TypeAdapter(DomainEvent)
