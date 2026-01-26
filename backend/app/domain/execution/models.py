from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import EventMetadata, ResourceUsageDomain


class DomainExecution(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    script: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    stdout: str | None = None
    stderr: str | None = None
    lang: str = "python"
    lang_version: str = "3.11"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: ResourceUsageDomain | None = None
    user_id: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None


class ExecutionResultDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    resource_usage: ResourceUsageDomain | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: EventMetadata | None = None
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

    status: ExecutionStatus | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    resource_usage: ResourceUsageDomain | None = None
