from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import ExecutionErrorType, ExecutionStatus, ReplayStatus
from app.domain.events import EventSummary, ResourceUsageDomain
from app.domain.replay import ReplayConfig, ReplayError, ReplayFilter


@dataclass
class ExecutionResultSummary:
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


@dataclass
class ReplaySessionStatusDetail:
    """Status detail with computed metadata for admin API."""

    session_id: str
    config: ReplayConfig
    status: ReplayStatus = ReplayStatus.CREATED
    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None
    errors: list[ReplayError] = field(default_factory=list)
    replay_id: str = ""
    created_by: str | None = None
    target_service: str | None = None
    dry_run: bool = False
    triggered_executions: list[str] = field(default_factory=list)
    error: str | None = None
    estimated_completion: datetime | None = None
    execution_results: list[ExecutionResultSummary] = field(default_factory=list)


@dataclass
class ReplaySessionStatusInfo:
    """Lightweight status info for API responses."""

    session_id: str
    status: ReplayStatus
    total_events: int
    replayed_events: int
    failed_events: int
    skipped_events: int
    replay_id: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    progress_percentage: float = 0.0


@dataclass
class ReplaySessionData:
    """Unified replay session data for both preview and actual replay."""

    total_events: int
    replay_id: str
    dry_run: bool
    filter: ReplayFilter
    events_preview: list[EventSummary] = field(default_factory=list)
