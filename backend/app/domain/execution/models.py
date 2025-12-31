from __future__ import annotations

from dataclasses import field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic.dataclasses import dataclass

from app.domain.enums.execution import ExecutionStatus
from app.domain.enums.storage import ExecutionErrorType


@dataclass
class ResourceUsageDomain:
    execution_time_wall_seconds: float = 0.0
    cpu_time_jiffies: int = 0
    clk_tck_hertz: int = 0
    peak_memory_kb: int = 0


@dataclass
class DomainExecution:
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    script: str = ""
    status: ExecutionStatus = ExecutionStatus.QUEUED
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    lang: str = "python"
    lang_version: str = "3.11"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resource_usage: Optional[ResourceUsageDomain] = None
    user_id: Optional[str] = None
    exit_code: Optional[int] = None
    error_type: Optional[ExecutionErrorType] = None


@dataclass
class ExecutionResultDomain:
    execution_id: str
    status: ExecutionStatus
    exit_code: int
    stdout: str
    stderr: str
    resource_usage: ResourceUsageDomain | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
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

    status: Optional[ExecutionStatus] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    error_type: Optional[ExecutionErrorType] = None
    resource_usage: Optional[ResourceUsageDomain] = None
