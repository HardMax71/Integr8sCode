from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType


class ResourceUsageDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_time_wall_seconds: float = 0.0
    cpu_time_jiffies: int = 0
    clk_tck_hertz: int = 0
    peak_memory_kb: int = 0


class DomainExecution(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    script: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    lang: str = "python"
    lang_version: str = "3.11"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: Optional[ResourceUsageDomain] = None
    user_id: Optional[str] = None
    exit_code: Optional[int] = None
    error_type: Optional[ExecutionErrorType] = None


class ExecutionResultDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    resource_usage: ResourceUsageDomain | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_type: ExecutionErrorType | None = None


class LanguageInfoDomain(BaseModel):
    """Language runtime information."""

    model_config = ConfigDict(from_attributes=True)

    versions: list[str]
    file_ext: str


class ResourceLimitsDomain(BaseModel):
    """K8s resource limits configuration."""

    model_config = ConfigDict(from_attributes=True)

    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_runtimes: dict[str, LanguageInfoDomain]


class DomainExecutionCreate(BaseModel):
    """Execution creation data for repository."""

    model_config = ConfigDict(from_attributes=True)

    script: str
    user_id: str
    lang: str = "python"
    lang_version: str = "3.11"
    status: ExecutionStatus = ExecutionStatus.QUEUED


class DomainExecutionUpdate(BaseModel):
    """Execution update data for repository."""

    model_config = ConfigDict(from_attributes=True)

    status: Optional[ExecutionStatus] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    error_type: Optional[ExecutionErrorType] = None
    resource_usage: Optional[ResourceUsageDomain] = None
