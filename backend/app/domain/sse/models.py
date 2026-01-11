from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums.execution import ExecutionStatus


class ShutdownStatus(BaseModel):
    """Status of SSE shutdown process."""

    model_config = ConfigDict(from_attributes=True)

    phase: str
    initiated: bool
    complete: bool
    active_connections: int
    draining_connections: int
    duration: float | None = None


class SSEHealthDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    kafka_enabled: bool
    active_connections: int
    active_executions: int
    active_consumers: int
    max_connections_per_user: int
    shutdown: ShutdownStatus
    timestamp: datetime


class SSEExecutionStatusDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: ExecutionStatus
    timestamp: datetime


class SSEEventDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: str
    timestamp: datetime
