from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums.execution import ExecutionStatus


class SSEExecutionStatusDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: ExecutionStatus
    timestamp: datetime


class SSEEventDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: str
    timestamp: datetime
