from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.enums import CancelStatus, ExecutionErrorType, ExecutionStatus, QueuePriority
from app.domain.events import EventMetadata, ResourceUsageDomain
from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION


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
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: ResourceUsageDomain | None = None
    user_id: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    priority: QueuePriority = QueuePriority.NORMAL


@dataclass
class ExecutionResultDomain:
    execution_id: str
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
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
class LanguageLimitsDomain:
    """Limits a pod for one language gets: the admin limits raised to the language minimums."""

    cpu_limit: str
    memory_limit: str
    execution_timeout: int


@dataclass
class ResourceLimitsDomain:
    """K8s resource limits configuration."""

    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    execution_timeout: int
    supported_runtimes: dict[str, LanguageInfoDomain]
    language_limits: dict[str, LanguageLimitsDomain]


@dataclass
class DomainExecutionCreate:
    """Execution creation data for repository."""

    script: str
    user_id: str
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
    status: ExecutionStatus = ExecutionStatus.QUEUED
    priority: QueuePriority = QueuePriority.NORMAL


@dataclass
class DomainExecutionUpdate:
    """Execution update data for repository."""

    status: ExecutionStatus | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    error_type: ExecutionErrorType | None = None
    resource_usage: ResourceUsageDomain | None = None
