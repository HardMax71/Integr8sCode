from dataclasses import field
from datetime import datetime

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from app.domain.enums import ExecutionStatus, ReplayStatus
from app.domain.events import EventSummary
from app.domain.replay import ReplayFilter, ReplaySessionState


@dataclass(config=ConfigDict(from_attributes=True))
class ExecutionResultSummary:
    """Summary of an execution result for replay status."""

    execution_id: str
    status: ExecutionStatus | None
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    lang: str
    lang_version: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ReplaySessionStatusDetail:
    """Status detail with computed metadata for admin API."""

    session: ReplaySessionState
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
    correlation_id: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    progress_percentage: float = 0.0


@dataclass
class ReplaySessionData:
    """Unified replay session data for both preview and actual replay."""

    total_events: int
    replay_correlation_id: str
    dry_run: bool
    filter: ReplayFilter
    events_preview: list[EventSummary] = field(default_factory=list)
