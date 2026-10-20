from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import CancelStatus, ExecutionErrorType, ExecutionStatus
from app.domain.events import ResourceUsageDomain
from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION


@dataclass
class CancelResult:
    execution_id: str
    status: CancelStatus
    message: str
    event_id: str | None


@dataclass
class ExecutionResultDomain:
    execution_id: str
    status: ExecutionStatus
    exit_code: int | None
    stdout: str | None
    stderr: str | None
    lang: str = DEFAULT_LANG
    lang_version: str = DEFAULT_LANG_VERSION
    resource_usage: ResourceUsageDomain | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
