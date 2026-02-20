from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ExecutionErrorType, ExecutionStatus, QueuePriority


class AdminExecutionResponse(BaseModel):
    """Execution with priority for admin views."""

    execution_id: str
    script: str
    status: ExecutionStatus
    lang: str
    lang_version: str
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    priority: QueuePriority = QueuePriority.NORMAL
    user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminExecutionListResponse(BaseModel):
    """Paginated list of executions for admin."""

    executions: list[AdminExecutionResponse]
    total: int
    limit: int
    skip: int
    has_more: bool


class PriorityUpdateRequest(BaseModel):
    """Request to update execution priority."""

    priority: QueuePriority = Field(description="New priority level")


class QueueStatusResponse(BaseModel):
    """Queue status summary."""

    queue_depth: int = Field(description="Number of pending executions")
    active_count: int = Field(description="Number of actively running executions")
    max_concurrent: int = Field(description="Maximum concurrent executions allowed")
    by_priority: dict[str, int] = Field(default_factory=dict, description="Pending count per priority")
