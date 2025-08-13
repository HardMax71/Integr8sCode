"""Event schemas for Kafka event streaming with Avro serialization.

This module contains all event schemas that inherit from AvroBase,
used for event-driven architecture with Kafka and schema registry.
"""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field
from pydantic_avro import AvroBase


class EventType(StrEnum):
    """Event types used throughout the system."""

    # Execution lifecycle events
    EXECUTION_REQUESTED = "execution_requested"
    EXECUTION_QUEUED = "execution_queued"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_RUNNING = "execution_running"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_TIMEOUT = "execution_timeout"
    EXECUTION_CANCELLED = "execution_cancelled"

    # Pod lifecycle events
    POD_CREATED = "pod_created"
    POD_SCHEDULED = "pod_scheduled"
    POD_RUNNING = "pod_running"
    POD_SUCCEEDED = "pod_succeeded"
    POD_FAILED = "pod_failed"
    POD_TERMINATED = "pod_terminated"
    POD_DELETED = "pod_deleted"

    # User events
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    USER_LOGGED_IN = "user_logged_in"
    USER_LOGGED_OUT = "user_logged_out"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"

    # User settings events
    USER_SETTINGS_UPDATED = "user_settings_updated"
    USER_PREFERENCES_UPDATED = "user_preferences_updated"
    USER_THEME_CHANGED = "user_theme_changed"
    USER_LANGUAGE_CHANGED = "user_language_changed"
    USER_NOTIFICATION_SETTINGS_UPDATED = "user_notification_settings_updated"
    USER_EDITOR_SETTINGS_UPDATED = "user_editor_settings_updated"

    # Notification events
    NOTIFICATION_CREATED = "notification_created"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_DELIVERED = "notification_delivered"
    NOTIFICATION_FAILED = "notification_failed"
    NOTIFICATION_READ = "notification_read"
    NOTIFICATION_CLICKED = "notification_clicked"
    NOTIFICATION_PREFERENCES_UPDATED = "notification_preferences_updated"

    # Script events
    SCRIPT_SAVED = "script_saved"
    SCRIPT_DELETED = "script_deleted"
    SCRIPT_SHARED = "script_shared"

    # Security events
    SECURITY_VIOLATION = "security_violation"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    AUTH_FAILED = "auth_failed"

    # Resource events
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    QUOTA_EXCEEDED = "quota_exceeded"

    # System events
    SYSTEM_ERROR = "system_error"
    SERVICE_UNHEALTHY = "service_unhealthy"
    SERVICE_RECOVERED = "service_recovered"

    # Result events
    RESULT_STORED = "result_stored"
    RESULT_FAILED = "result_failed"


class KafkaTopic(StrEnum):
    """Kafka topic names used throughout the system."""

    # Execution topics
    EXECUTION_EVENTS = "execution_events"
    EXECUTION_RESULTS = "execution_results"
    EXECUTION_REQUESTS = "execution_requests"
    EXECUTION_COMMANDS = "execution_commands"
    EXECUTION_TASKS = "execution_tasks"

    # Pod topics
    POD_EVENTS = "pod_events"
    POD_STATUS_UPDATES = "pod_status_updates"
    POD_RESULTS = "pod_results"

    # Result topics
    RESULT_EVENTS = "result_events"

    # User topics
    USER_EVENTS = "user_events"
    USER_NOTIFICATIONS = "user_notifications"
    USER_SETTINGS_EVENTS = "user_settings_events"

    # Script topics
    SCRIPT_EVENTS = "script_events"

    # Security topics
    SECURITY_EVENTS = "security_events"

    # Resource topics
    RESOURCE_EVENTS = "resource_events"

    # Notification topics
    NOTIFICATION_EVENTS = "notification_events"

    # System topics
    SYSTEM_EVENTS = "system_events"

    # Saga topics
    SAGA_EVENTS = "saga_events"

    # Infrastructure topics
    DEAD_LETTER_QUEUE = "dead_letter_queue"
    EVENT_BUS_STREAM = "event_bus_stream"
    WEBSOCKET_EVENTS = "websocket_events"


# Event type to Kafka topic mapping
EVENT_TYPE_TO_TOPIC: dict[EventType, KafkaTopic] = {
    # Execution lifecycle events
    EventType.EXECUTION_REQUESTED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_QUEUED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_STARTED: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_RUNNING: KafkaTopic.EXECUTION_EVENTS,
    EventType.EXECUTION_COMPLETED: KafkaTopic.EXECUTION_RESULTS,
    EventType.EXECUTION_FAILED: KafkaTopic.EXECUTION_RESULTS,
    EventType.EXECUTION_TIMEOUT: KafkaTopic.EXECUTION_RESULTS,
    EventType.EXECUTION_CANCELLED: KafkaTopic.EXECUTION_EVENTS,

    # Pod lifecycle events
    EventType.POD_CREATED: KafkaTopic.POD_EVENTS,
    EventType.POD_SCHEDULED: KafkaTopic.POD_EVENTS,
    EventType.POD_RUNNING: KafkaTopic.POD_STATUS_UPDATES,
    EventType.POD_SUCCEEDED: KafkaTopic.POD_STATUS_UPDATES,
    EventType.POD_FAILED: KafkaTopic.POD_STATUS_UPDATES,
    EventType.POD_TERMINATED: KafkaTopic.POD_STATUS_UPDATES,
    EventType.POD_DELETED: KafkaTopic.POD_EVENTS,

    # Result events
    EventType.RESULT_STORED: KafkaTopic.RESULT_EVENTS,
    EventType.RESULT_FAILED: KafkaTopic.RESULT_EVENTS,

    # User events
    EventType.USER_REGISTERED: KafkaTopic.USER_EVENTS,
    EventType.USER_LOGIN: KafkaTopic.USER_EVENTS,
    EventType.USER_LOGGED_IN: KafkaTopic.USER_EVENTS,
    EventType.USER_LOGGED_OUT: KafkaTopic.USER_EVENTS,
    EventType.USER_UPDATED: KafkaTopic.USER_EVENTS,
    EventType.USER_DELETED: KafkaTopic.USER_EVENTS,

    # User settings events
    EventType.USER_SETTINGS_UPDATED: KafkaTopic.USER_SETTINGS_EVENTS,
    EventType.USER_PREFERENCES_UPDATED: KafkaTopic.USER_SETTINGS_EVENTS,
    EventType.USER_THEME_CHANGED: KafkaTopic.USER_SETTINGS_EVENTS,
    EventType.USER_LANGUAGE_CHANGED: KafkaTopic.USER_SETTINGS_EVENTS,
    EventType.USER_NOTIFICATION_SETTINGS_UPDATED: KafkaTopic.USER_SETTINGS_EVENTS,
    EventType.USER_EDITOR_SETTINGS_UPDATED: KafkaTopic.USER_SETTINGS_EVENTS,

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
}


def get_topic_for_event(event_type: EventType | str) -> KafkaTopic:
    """Get the Kafka topic for a given event type."""
    if isinstance(event_type, str):
        event_type = EventType(event_type)
    return EVENT_TYPE_TO_TOPIC.get(event_type, KafkaTopic.SYSTEM_EVENTS)


def get_all_topics() -> set[KafkaTopic]:
    """Get all defined Kafka topics."""
    return set(KafkaTopic)


def get_topic_configs() -> dict[KafkaTopic, dict[str, Any]]:
    """Get configuration for all Kafka topics."""
    return {
        # High-volume execution topics
        KafkaTopic.EXECUTION_EVENTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_RESULTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_REQUESTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_COMMANDS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EXECUTION_TASKS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },

        # Pod lifecycle topics
        KafkaTopic.POD_EVENTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.POD_STATUS_UPDATES: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.POD_RESULTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Result topics
        KafkaTopic.RESULT_EVENTS: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # User topics
        KafkaTopic.USER_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_NOTIFICATIONS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "259200000",  # 3 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.USER_SETTINGS_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },

        # Script topics
        KafkaTopic.SCRIPT_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Security topics
        KafkaTopic.SECURITY_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "2592000000",  # 30 days
                "compression.type": "gzip",
            }
        },

        # Resource topics
        KafkaTopic.RESOURCE_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Notification topics
        KafkaTopic.NOTIFICATION_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "259200000",  # 3 days
                "compression.type": "gzip",
            }
        },

        # System topics
        KafkaTopic.SYSTEM_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Saga topics
        KafkaTopic.SAGA_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "604800000",  # 7 days
                "compression.type": "gzip",
            }
        },

        # Infrastructure topics
        KafkaTopic.DEAD_LETTER_QUEUE: {
            "num_partitions": 3,
            "replication_factor": 1,
            "config": {
                "retention.ms": "1209600000",  # 14 days
                "compression.type": "gzip",
            }
        },
        KafkaTopic.EVENT_BUS_STREAM: {
            "num_partitions": 10,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
        KafkaTopic.WEBSOCKET_EVENTS: {
            "num_partitions": 5,
            "replication_factor": 1,
            "config": {
                "retention.ms": "86400000",  # 1 day
                "compression.type": "gzip",
            }
        },
    }


# Enums for bounded values
class ExecutionErrorType(StrEnum):
    """Types of execution errors."""
    SYSTEM_ERROR = "system_error"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    SCRIPT_ERROR = "script_error"
    PERMISSION_DENIED = "permission_denied"


class StorageType(StrEnum):
    """Types of storage backends."""
    DATABASE = "database"
    S3 = "s3"
    FILESYSTEM = "filesystem"
    REDIS = "redis"


class LoginMethod(StrEnum):
    """User login methods."""
    PASSWORD = "password"
    OAUTH = "oauth"
    SSO = "sso"
    API_KEY = "api_key"


class SettingsType(StrEnum):
    """Types of user settings."""
    PREFERENCES = "preferences"
    NOTIFICATION = "notification"
    EDITOR = "editor"
    SECURITY = "security"
    DISPLAY = "display"


class NotificationType(StrEnum):
    """Types of notifications."""
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    SYSTEM_ALERT = "system_alert"
    SECURITY_ALERT = "security_alert"
    QUOTA_WARNING = "quota_warning"
    MAINTENANCE = "maintenance"


class NotificationPriority(StrEnum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationChannel(StrEnum):
    """Notification delivery channels."""
    EMAIL = "email"
    PUSH = "push"
    IN_APP = "in_app"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationProvider(StrEnum):
    """Notification service providers."""
    SENDGRID = "sendgrid"
    FCM = "fcm"
    APNS = "apns"
    TWILIO = "twilio"
    INTERNAL = "internal"


class SecuritySeverity(StrEnum):
    """Security violation severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResourceType(StrEnum):
    """Types of computational resources."""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    EXECUTION_TIME = "execution_time"
    NETWORK = "network"
    API_CALLS = "api_calls"


class ResourceAction(StrEnum):
    """Actions taken on resource limit violations."""
    REJECTED = "rejected"
    THROTTLED = "throttled"
    QUEUED = "queued"
    TERMINATED = "terminated"


class Environment(StrEnum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class NotificationStatus(StrEnum):
    """Status of notification delivery."""
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    PENDING = "pending"
    BOUNCED = "bounced"


class EventMetadata(AvroBase):
    """Metadata for event auditing and tracing."""
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    service_name: str
    service_version: str
    environment: Environment = Environment.PRODUCTION

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                "causation_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "user_id": "user123",
                "session_id": "session456",
                "ip_address": "192.168.1.1",
                "user_agent": "Mozilla/5.0",
                "service_name": "execution-service",
                "service_version": "1.0.0",
                "environment": "production"
            }
        }
    )


class BaseEvent(AvroBase):
    """Base class for all events."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None
    metadata: EventMetadata

    model_config = ConfigDict(
        use_enum_values=True,
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return self.model_dump(by_alias=True)

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return self.model_dump_json(by_alias=True)


# Execution Events

class ExecutionRequestedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_REQUESTED] = EventType.EXECUTION_REQUESTED

    execution_id: str
    script: str
    language: str
    language_version: str
    runtime_image: str
    runtime_command: list[str]
    runtime_filename: str
    timeout_seconds: int | None = None
    cpu_limit: str | None = None
    memory_limit: str | None = None
    cpu_request: str | None = None
    memory_request: str | None = None
    priority: int = 5
    environment_variables: dict[str, str] | None = None
    stdin: str | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": EventType.EXECUTION_REQUESTED,
                "execution_id": "550e8400-e29b-41d4-a716-446655440000",
                "script": "print('Hello, World!')",
                "language": "python",
                "language_version": "3.11",
                "runtime_image": "python:3.11-slim",
                "runtime_command": ["python"],
                "runtime_filename": "main.py",
                "timeout_seconds": 30,
                "cpu_limit": "100m",
                "memory_limit": "128Mi",
                "cpu_request": "50m",
                "memory_request": "64Mi",
                "priority": 5
            }
        }
    )


class ExecutionStartedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_STARTED] = EventType.EXECUTION_STARTED

    execution_id: str
    pod_name: str
    node_name: str | None = None
    container_id: str | None = None


class ExecutionCompletedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_COMPLETED] = EventType.EXECUTION_COMPLETED

    execution_id: str
    exit_code: int
    output: str
    runtime_ms: int


class ExecutionFailedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_FAILED] = EventType.EXECUTION_FAILED

    execution_id: str
    error: str
    error_type: ExecutionErrorType
    exit_code: int | None = None
    output: str | None = None


class ExecutionTimeoutEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_TIMEOUT] = EventType.EXECUTION_TIMEOUT

    execution_id: str
    timeout_seconds: int
    partial_output: str | None = None


class ExecutionCancelledEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_CANCELLED] = EventType.EXECUTION_CANCELLED

    execution_id: str
    reason: str
    cancelled_by: str | None = None
    force_terminated: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "execution.cancelled",
                "execution_id": "550e8400-e29b-41d4-a716-446655440000",
                "reason": "user_requested",
                "cancelled_by": "user123",
                "force_terminated": False
            }
        }
    )


# Pod Events

class PodCreatedEvent(BaseEvent):
    event_type: Literal[EventType.POD_CREATED] = EventType.POD_CREATED

    execution_id: str
    pod_name: str
    namespace: str


class PodScheduledEvent(BaseEvent):
    event_type: Literal[EventType.POD_SCHEDULED] = EventType.POD_SCHEDULED

    execution_id: str
    pod_name: str
    node_name: str


class PodRunningEvent(BaseEvent):
    event_type: Literal[EventType.POD_RUNNING] = EventType.POD_RUNNING

    execution_id: str
    pod_name: str
    container_statuses: list[dict[str, Any]]


class PodTerminatedEvent(BaseEvent):
    event_type: Literal[EventType.POD_TERMINATED] = EventType.POD_TERMINATED

    execution_id: str
    pod_name: str
    exit_code: int
    reason: str | None = None
    message: str | None = None


class PodSucceededEvent(BaseEvent):
    event_type: Literal[EventType.POD_SUCCEEDED] = EventType.POD_SUCCEEDED

    execution_id: str
    pod_name: str
    completion_time: datetime


class PodFailedEvent(BaseEvent):
    event_type: Literal[EventType.POD_FAILED] = EventType.POD_FAILED

    execution_id: str
    pod_name: str
    reason: str
    message: str | None = None
    exit_code: int | None = None


# Result Events

class ResultStoredEvent(BaseEvent):
    event_type: Literal[EventType.RESULT_STORED] = EventType.RESULT_STORED

    execution_id: str
    storage_key: str
    size_bytes: int
    storage_type: StorageType = StorageType.DATABASE


class ResultFailedEvent(BaseEvent):
    event_type: Literal[EventType.RESULT_FAILED] = EventType.RESULT_FAILED

    execution_id: str
    error: str
    partial_result: str | None = None


# User Events

class UserLoggedInEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGGED_IN] = EventType.USER_LOGGED_IN

    user_id: str
    login_method: LoginMethod = LoginMethod.PASSWORD
    ip_address: str
    user_agent: str


class UserLoggedOutEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGGED_OUT] = EventType.USER_LOGGED_OUT

    user_id: str
    session_duration_seconds: int


class UserSettingsUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_SETTINGS_UPDATED] = EventType.USER_SETTINGS_UPDATED

    user_id: str
    settings_type: SettingsType
    changed_fields: list[str]
    old_values: dict[str, Any]
    new_values: dict[str, Any]


# Notification Events

class NotificationCreatedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_CREATED] = EventType.NOTIFICATION_CREATED

    notification_id: str
    user_id: str
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.NORMAL
    title: str
    message: str
    data: dict[str, Any] | None = None


class NotificationSentEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_SENT] = EventType.NOTIFICATION_SENT

    notification_id: str
    user_id: str
    channel: NotificationChannel
    provider: NotificationProvider
    status: NotificationStatus = NotificationStatus.SENT


# System Events

class SystemErrorEvent(BaseEvent):
    event_type: Literal[EventType.SYSTEM_ERROR] = EventType.SYSTEM_ERROR

    error_type: str
    service_name: str
    error_message: str
    stack_trace: str | None = None
    context: dict[str, Any] | None = None


class RateLimitExceededEvent(BaseEvent):
    event_type: Literal[EventType.RATE_LIMIT_EXCEEDED] = EventType.RATE_LIMIT_EXCEEDED

    user_id: str | None = None
    ip_address: str
    endpoint: str
    limit: int
    window_seconds: int
    current_count: int


# User Registration Event

class UserRegisteredEvent(BaseEvent):
    event_type: Literal[EventType.USER_REGISTERED] = EventType.USER_REGISTERED

    user_id: str
    username: str
    email: str
    registration_method: str = "email"
    created_at: datetime


# Script Events

class ScriptSavedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_SAVED] = EventType.SCRIPT_SAVED

    script_id: str
    user_id: str
    name: str
    language: str
    description: str | None = None
    is_public: bool = False
    tags: list[str] = Field(default_factory=list)


# Security Events

class SecurityViolationEvent(BaseEvent):
    event_type: Literal[EventType.SECURITY_VIOLATION] = EventType.SECURITY_VIOLATION

    violation_type: str
    user_id: str | None = None
    ip_address: str
    resource: str
    action: str
    reason: str
    severity: SecuritySeverity = SecuritySeverity.MEDIUM


# Resource Events

class ResourceLimitExceededEvent(BaseEvent):
    event_type: Literal[EventType.RESOURCE_LIMIT_EXCEEDED] = EventType.RESOURCE_LIMIT_EXCEEDED

    resource_type: ResourceType
    limit_value: float
    requested_value: float
    execution_id: str | None = None
    user_id: str | None = None
    action_taken: ResourceAction = ResourceAction.REJECTED


# Helper functions for event type mapping and deserialization

def build_event_type_mapping() -> dict[EventType, type[BaseEvent]]:
    """Build event type to class mapping dynamically from all BaseEvent subclasses.
    
    This avoids maintaining a manual mapping that can get out of sync.
    """
    mapping = {}
    for subclass in BaseEvent.__subclasses__():
        # Get the default value of event_type field
        if 'event_type' in subclass.model_fields:
            event_type_field = subclass.model_fields['event_type']
            if event_type_field.default is not None:
                mapping[event_type_field.default] = subclass
    return mapping


def deserialize_event(event_data: dict[str, Any]) -> BaseEvent:
    """Deserialize event data to appropriate event class."""
    event_type_mapping = build_event_type_mapping()

    event_type_str = event_data.get('event_type')
    if not event_type_str:
        raise ValueError("Missing event_type in event data")

    event_type = EventType(event_type_str)
    event_class = event_type_mapping.get(event_type)
    if not event_class:
        raise ValueError(f"No event class found for event type: {event_type}")

    return event_class.model_validate(event_data)
