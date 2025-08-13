"""Pydantic schemas for SSE endpoints."""
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SSEEvent(BaseModel):
    """Base model for SSE events."""
    event: str = Field(description="Event type")
    data: str = Field(description="JSON-encoded event data")


class SSEHealthResponse(BaseModel):
    """Response model for SSE health check."""
    status: str = Field(description="Health status: healthy or draining")
    kafka_enabled: bool = Field(True, description="Whether Kafka features are enabled")
    active_connections: int = Field(description="Total number of active SSE connections")
    active_executions: int = Field(description="Number of executions being monitored")
    active_consumers: int = Field(description="Number of active Kafka consumers")
    max_connections_per_user: int = Field(description="Maximum connections allowed per user")
    shutdown: Dict[str, Any] = Field(description="Shutdown status information")
    timestamp: datetime = Field(description="Health check timestamp")


class ExecutionStreamEvent(BaseModel):
    """Model for execution stream events."""
    event_id: Optional[str] = Field(None, description="Unique event identifier")
    timestamp: Optional[str] = Field(None, description="Event timestamp")
    type: Optional[str] = Field(None, description="Event type")
    execution_id: str = Field(description="Execution ID")
    status: Optional[str] = Field(None, description="Execution status")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event payload")
    output: Optional[str] = Field(None, description="Execution output")
    errors: Optional[str] = Field(None, description="Execution errors")


class NotificationStreamEvent(BaseModel):
    """Model for notification stream events."""
    message: str = Field(description="Notification message")
    user_id: str = Field(description="User ID")
    timestamp: str = Field(description="Event timestamp")


class HeartbeatEvent(BaseModel):
    """Model for heartbeat events."""
    timestamp: str = Field(description="Heartbeat timestamp")
    execution_id: Optional[str] = Field(None, description="Associated execution ID")
    user_id: Optional[str] = Field(None, description="Associated user ID")
    message: Optional[str] = Field(None, description="Optional heartbeat message")
