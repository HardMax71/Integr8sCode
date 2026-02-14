from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.enums import CancelStatus, ExecutionErrorType, ExecutionStatus
from app.domain.events import EventMetadata, ResourceUsageDomain


@dataclass
class CancelResult:
    execution_id: str
    status: CancelStatus
    message: str
    event_id: str | None


@dataclass
class DomainExecution:
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    script: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    stdout: str | None = None
    stderr: str | None = None
    lang: str = "python"
    lang_version: str = "3.11"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: ResourceUsageDomain | None = None
    user_id: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None


@dataclass
class ExecutionResultDomain:
    execution_id: str
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    lang: str = "python"
    lang_version: str = "3.11"
    resource_usage: ResourceUsageDomain | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: EventMetadata | None = None
    error_type: ExecutionErrorType | None = None


@dataclass
class LanguageInfoDomain:
    """Language runtime information."""

    versions: list[str]
    file_ext: str


@dataclass
class ResourceLimitsDomain:
    """K8s resource limits configuration."""

    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_runtimes: dict[str, LanguageInfoDomain]


@dataclass
class DomainExecutionCreate:
    """Execution creation data for repository."""

    script: str
    user_id: str
    lang: str = "python"
    lang_version: str = "3.11"
    status: ExecutionStatus = ExecutionStatus.QUEUED


@dataclass
class DomainExecutionUpdate:
    """Execution update data for repository."""

    status: ExecutionStatus | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    resource_usage: ResourceUsageDomain | None = None
