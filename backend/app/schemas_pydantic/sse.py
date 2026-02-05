from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.notification import NotificationSeverity, NotificationStatus
from app.domain.enums.sse import SSEControlEvent
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
    timestamp: datetime | None = Field(default=None, description="Event timestamp")

    # Present in business events from Kafka
    event_id: str | None = Field(default=None, description="Unique event identifier")

    # Control event specific fields
    connection_id: str | None = Field(default=None, description="SSE connection ID (connected event)")
    message: str | None = Field(default=None, description="Human-readable message (subscribed event)")

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

    event_type: str = Field(description="Event topic name from Kafka")
    execution_id: str | None = Field(None, description="Execution ID")
    data: dict[str, Any] = Field(description="Full event data from BaseEvent.model_dump()")


class RedisNotificationMessage(BaseModel):
    """Message structure published to Redis for notification SSE delivery."""

    notification_id: str = Field(description="Unique notification ID")
    severity: NotificationSeverity = Field(description="Notification severity level")
    status: NotificationStatus = Field(description="Notification delivery status")
    tags: list[str] = Field(default_factory=list, description="Notification tags")
    subject: str = Field(description="Notification subject/title")
    body: str = Field(description="Notification body content")
    action_url: str = Field(default="", description="Optional action URL")
    created_at: datetime = Field(description="Creation timestamp")
