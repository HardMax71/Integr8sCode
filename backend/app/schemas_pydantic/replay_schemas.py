from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ExecutionErrorType, ExecutionStatus
from app.domain.events.typed import ResourceUsageDomain


class ExecutionResultSummary(BaseModel):
    """Summary of an execution result for replay status."""

    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: ExecutionStatus | None
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    lang: str
    lang_version: str
    created_at: datetime
    updated_at: datetime
    resource_usage: ResourceUsageDomain | None = None
    error_type: ExecutionErrorType | None = None
