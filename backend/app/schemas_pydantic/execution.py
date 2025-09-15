from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums.common import ErrorType
from app.domain.enums.execution import ExecutionStatus
from app.settings import get_settings


class ExecutionBase(BaseModel):
    """Base model for execution data."""
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    status: ExecutionStatus = ExecutionStatus.QUEUED
    stdout: str | None = None
    stderr: str | None = None
    lang: str = "python"
    lang_version: str = "3.11"


class ExecutionCreate(ExecutionBase):
    """Model for creating a new execution."""
    pass


class ExecutionInDB(ExecutionBase):
    """Model for execution as stored in database."""
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: dict | None = None
    user_id: str | None = None
    exit_code: int | None = None
    error_type: ErrorType | None = None

    model_config = ConfigDict(
        populate_by_name=True
    )


class ExecutionUpdate(BaseModel):
    """Model for updating an execution."""
    status: ExecutionStatus | None = None
    stdout: str | None = None
    stderr: str | None = None
    resource_usage: dict | None = None
    exit_code: int | None = None
    error_type: ErrorType | None = None


class ResourceUsage(BaseModel):
    """Model for execution resource usage."""
    execution_time_wall_seconds: float | None = Field(
        default=None, description="Wall clock execution time in seconds"
    )
    cpu_time_jiffies: int | None = Field(
        default=None, description="CPU time in jiffies (multiply by 10 for milliseconds)"
    )
    clk_tck_hertz: int | None = Field(
        default=None, description="Clock ticks per second (usually 100)"
    )
    peak_memory_kb: int | None = Field(
        default=None, description="Peak memory usage in KB"
    )


class ExecutionRequest(BaseModel):
    """Model for execution request."""
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    lang: str = Field(
        default="python", description="Language name"
    )
    lang_version: str = Field(
        default="3.11", description="Language version to use for execution"
    )

    @model_validator(mode="after")
    def validate_runtime_supported(self) -> "ExecutionRequest":  # noqa: D401
        settings = get_settings()
        runtimes = settings.SUPPORTED_RUNTIMES or {}
        if self.lang not in runtimes:
            raise ValueError(f"Language '{self.lang}' not supported. Supported: {list(runtimes.keys())}")
        versions = runtimes.get(self.lang, [])
        if self.lang_version not in versions:
            raise ValueError(
                f"Version '{self.lang_version}' not supported for {self.lang}. Supported: {versions}"
            )
        return self


class ExecutionResponse(BaseModel):
    """Model for execution response."""
    execution_id: str
    status: ExecutionStatus

    model_config = ConfigDict(
        from_attributes=True
    )


class ExecutionResult(BaseModel):
    """Model for execution result."""
    execution_id: str
    status: ExecutionStatus
    stdout: str | None = None
    stderr: str | None = None
    lang: str
    lang_version: str
    resource_usage: ResourceUsage | None = None
    exit_code: int | None = None
    error_type: ErrorType | None = None

    model_config = ConfigDict(
        from_attributes=True
    )


class ResourceLimits(BaseModel):
    """Model for resource limits configuration."""
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_runtimes: dict[str, list[str]]


class ExampleScripts(BaseModel):
    """Model for example scripts."""
    scripts: dict[str, str]  # lang: str with script


class CancelExecutionRequest(BaseModel):
    """Model for cancelling an execution."""
    reason: str | None = Field(None, description="Reason for cancellation")


class RetryExecutionRequest(BaseModel):
    """Model for retrying an execution."""
    reason: str | None = Field(None, description="Reason for retry")
    preserve_output: bool = Field(False, description="Keep output from previous attempt")


class ExecutionEventResponse(BaseModel):
    """Model for execution event response."""
    event_id: str
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]


class ExecutionListResponse(BaseModel):
    """Model for paginated execution list."""
    executions: list[ExecutionResult]
    total: int
    limit: int
    skip: int
    has_more: bool


class CancelResponse(BaseModel):
    """Model for execution cancellation response."""
    execution_id: str
    status: str
    message: str
    event_id: str | None = Field(None, description="Event ID for the cancellation event, if published")


class DeleteResponse(BaseModel):
    """Model for execution deletion response."""
    message: str
    execution_id: str
