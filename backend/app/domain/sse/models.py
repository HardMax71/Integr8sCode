from __future__ import annotations

from datetime import datetime

from pydantic.dataclasses import dataclass

from app.domain.enums.execution import ExecutionStatus


@dataclass
class ShutdownStatus:
    """Status of SSE shutdown process."""

    phase: str
    initiated: bool
    complete: bool
    active_connections: int
    draining_connections: int
    duration: float | None = None


@dataclass
class SSEHealthDomain:
    status: str
    kafka_enabled: bool
    active_connections: int
    active_executions: int
    active_consumers: int
    max_connections_per_user: int
    shutdown: ShutdownStatus
    timestamp: datetime


@dataclass
class SSEExecutionStatusDomain:
    execution_id: str
    status: ExecutionStatus
    timestamp: str


@dataclass
class SSEEventDomain:
    aggregate_id: str
    timestamp: datetime
