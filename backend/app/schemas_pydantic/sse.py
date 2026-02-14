from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EventType, ExecutionStatus, SSEControlEvent
from app.domain.events.typed import ResourceUsageDomain
from app.domain.execution.models import DomainExecution
from app.domain.sse.models import (
    RedisNotificationMessage,
    RedisSSEMessage,
)


class SSEExecutionEventData(BaseModel):
    """API schema for SSE execution stream event payload (OpenAPI docs)."""

    model_config = ConfigDict(from_attributes=True)

    event_type: EventType | SSEControlEvent = Field(
        description="Event type identifier (business event or control event)"
    )
    execution_id: str = Field(description="Execution ID this event relates to")
    timestamp: datetime | None = Field(default=None, description="Event timestamp")
    event_id: str | None = Field(default=None, description="Unique event identifier")
    connection_id: str | None = Field(default=None, description="SSE connection ID (connected event)")
    message: str | None = Field(default=None, description="Human-readable message (subscribed event)")
    status: ExecutionStatus | None = Field(default=None, description="Current execution status")
    stdout: str | None = Field(default=None, description="Standard output from execution")
    stderr: str | None = Field(default=None, description="Standard error from execution")
    exit_code: int | None = Field(default=None, description="Process exit code")
    timeout_seconds: int | None = Field(default=None, description="Timeout duration in seconds")
    resource_usage: ResourceUsageDomain | None = Field(default=None, description="CPU/memory usage metrics")
    result: DomainExecution | None = Field(default=None, description="Complete execution result")


__all__ = [
    "SSEExecutionEventData",
    "RedisSSEMessage",
    "RedisNotificationMessage",
]
