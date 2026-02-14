from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import ExecutionStatus


@dataclass
class SSEExecutionStatusDomain:
    execution_id: str
    status: ExecutionStatus
    timestamp: datetime


@dataclass
class SSEEventDomain:
    aggregate_id: str
    timestamp: datetime
