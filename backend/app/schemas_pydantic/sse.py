from datetime import datetime
from typing import Any, Dict, TypeVar

from pydantic import BaseModel, Field

from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.domain.enums.sse import SSEControlEvent, SSENotificationEvent
from app.schemas_pydantic.execution import ExecutionResult, ResourceUsage

# Type variable for generic Redis message parsing
T = TypeVar("T", bound=BaseModel)


class SSEExecutionEventData(BaseModel):
    """Typed model for SSE execution stream event payload.

    This represents the JSON data sent inside each SSE message for execution streams.
    All fields except event_type and execution_id are optional since different
    event types carry different data.
    """

    # Always present - identifies the event
    event_type: EventType | SSEControlEvent = Field(
        description="Event type identifier (business event or control event)"
    )
    execution_id: str = Field(description="Execution ID this event relates to")

    # Present in most events
    timestamp: str | None = Field(default=None, description="ISO 8601 timestamp")

    # Present in business events from Kafka
    event_id: str | None = Field(default=None, description="Unique event identifier")

    # Control event specific fields
    connection_id: str | None = Field(default=None, description="SSE connection ID (connected event)")
    message: str | None = Field(default=None, description="Human-readable message (heartbeat, shutdown)")
    grace_period: int | None = Field(default=None, description="Shutdown grace period in seconds")
    error: str | None = Field(default=None, description="Error message (error event)")

    # Execution status
    status: ExecutionStatus | None = Field(default=None, description="Current execution status")

    # Execution output (completed/failed/timeout events)
    stdout: str | None = Field(default=None, description="Standard output from execution")
    stderr: str | None = Field(default=None, description="Standard error from execution")
    exit_code: int | None = Field(default=None, description="Process exit code")
    timeout_seconds: int | None = Field(default=None, description="Timeout duration in seconds")

    # Resource usage metrics
    resource_usage: ResourceUsage | None = Field(default=None, description="CPU/memory usage metrics")

    # Full execution result (only for result_stored event)
    result: ExecutionResult | None = Field(default=None, description="Complete execution result")


class RedisSSEMessage(BaseModel):
    """Message structure published to Redis for execution SSE delivery."""

    event_type: EventType = Field(description="Event type from Kafka")
    execution_id: str | None = Field(None, description="Execution ID")
    data: Dict[str, Any] = Field(description="Full event data from BaseEvent.model_dump()")


class SSENotificationEventData(BaseModel):
    """Typed model for SSE notification stream event payload.

    This represents the JSON data sent inside each SSE message for notification streams.
    """

    # Always present - identifies the event type
    event_type: SSENotificationEvent = Field(description="SSE notification event type")

    # Present in control events (connected, heartbeat)
    user_id: str | None = Field(default=None, description="User ID for the notification stream")
    timestamp: str | None = Field(default=None, description="ISO 8601 timestamp")
    message: str | None = Field(default=None, description="Human-readable message")

    # Present only in notification events
    notification_id: str | None = Field(default=None, description="Unique notification ID")
    severity: NotificationSeverity | None = Field(default=None, description="Notification severity level")
    status: NotificationStatus | None = Field(default=None, description="Notification delivery status")
    tags: list[str] | None = Field(default=None, description="Notification tags")
    subject: str | None = Field(default=None, description="Notification subject/title")
    body: str | None = Field(default=None, description="Notification body content")
    action_url: str | None = Field(default=None, description="Optional action URL")
    created_at: str | None = Field(default=None, description="ISO 8601 creation timestamp")


class RedisNotificationMessage(BaseModel):
    """Message structure published to Redis for notification SSE delivery."""

    notification_id: str = Field(description="Unique notification ID")
    severity: NotificationSeverity = Field(description="Notification severity level")
    status: NotificationStatus = Field(description="Notification delivery status")
    tags: list[str] = Field(default_factory=list, description="Notification tags")
    subject: str = Field(description="Notification subject/title")
    body: str = Field(description="Notification body content")
    action_url: str = Field(default="", description="Optional action URL")
    created_at: str = Field(description="ISO 8601 creation timestamp")


class ShutdownStatusResponse(BaseModel):
    """Response model for shutdown status."""

    phase: str = Field(description="Current shutdown phase")
    initiated: bool = Field(description="Whether shutdown has been initiated")
    complete: bool = Field(description="Whether shutdown is complete")
    active_connections: int = Field(description="Number of active connections")
    draining_connections: int = Field(description="Number of connections being drained")
    duration: float | None = Field(None, description="Duration of shutdown in seconds")


class SSEHealthResponse(BaseModel):
    """Response model for SSE health check."""

    status: str = Field(description="Health status: healthy or draining")
    kafka_enabled: bool = Field(True, description="Whether Kafka features are enabled")
    active_connections: int = Field(description="Total number of active SSE connections")
    active_executions: int = Field(description="Number of executions being monitored")
    active_consumers: int = Field(description="Number of active Kafka consumers")
    max_connections_per_user: int = Field(description="Maximum connections allowed per user")
    shutdown: ShutdownStatusResponse = Field(description="Shutdown status information")
    timestamp: datetime = Field(description="Health check timestamp")
