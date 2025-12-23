from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field


class SSEEvent(BaseModel):
    """Base model for SSE events."""

    event: str = Field(description="Event type")
    data: str = Field(description="JSON-encoded event data")


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


class ExecutionStreamEvent(BaseModel):
    """Model for execution stream events."""

    event_id: str | None = Field(None, description="Unique event identifier")
    timestamp: datetime | None = Field(None, description="Event timestamp")
    type: str | None = Field(None, description="Event type")
    execution_id: str = Field(description="Execution ID")
    status: str | None = Field(None, description="Execution status")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event payload")
    stdout: str | None = Field(None, description="Execution stdout")
    stderr: str | None = Field(None, description="Execution stderr")


class NotificationStreamEvent(BaseModel):
    """Model for notification stream events."""

    message: str = Field(description="Notification message")
    user_id: str = Field(description="User ID")
    timestamp: datetime = Field(description="Event timestamp")


class HeartbeatEvent(BaseModel):
    """Model for heartbeat events."""

    timestamp: datetime = Field(description="Heartbeat timestamp")
    execution_id: str | None = Field(None, description="Associated execution ID")
    user_id: str | None = Field(None, description="Associated user ID")
    message: str | None = Field(None, description="Optional heartbeat message")
