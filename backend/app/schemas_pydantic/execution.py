"""Execution-related schemas for REST API endpoints.

This module contains Pydantic models for execution-related API requests and responses.
"""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_pydantic.error_types import ErrorType


class ExecutionStatus(StrEnum):
    """Status of an execution."""
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    ERROR = "error"


class ExecutionBase(BaseModel):
    """Base model for execution data."""
    script: str = Field(..., max_length=50000, description="Script content (max 50,000 characters)")
    status: ExecutionStatus = ExecutionStatus.QUEUED
    output: str | None = None
    errors: str | None = None
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
    output: str | None = None
    errors: str | None = None
    resource_usage: dict | None = None
    exit_code: int | None = None
    error_type: ErrorType | None = None


class ResourceUsage(BaseModel):
    """Model for execution resource usage."""
    cpu_usage: float | None = Field(
        default=None, description="Current CPU usage (in cores or percentage)"
    )
    memory_usage: float | None = Field(
        default=None, description="Current memory usage (in MB or GB)"
    )
    execution_time: float | None = Field(
        default=None, description="Total execution time in seconds"
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
    output: str | None = None
    errors: str | None = None
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
