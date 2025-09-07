from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict


@dataclass
class SSEHealthDomain:
    status: str
    kafka_enabled: bool
    active_connections: int
    active_executions: int
    active_consumers: int
    max_connections_per_user: int
    shutdown: Dict[str, Any]
    timestamp: datetime


@dataclass
class SSEExecutionStatusDomain:
    execution_id: str
    status: str
    timestamp: str


@dataclass
class SSEEventDomain:
    aggregate_id: str
    timestamp: Any
