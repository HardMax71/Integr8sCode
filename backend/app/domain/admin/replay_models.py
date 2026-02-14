from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.enums import ReplayStatus
from app.domain.events import EventSummary
from app.domain.replay import ReplayFilter, ReplaySessionState
from app.schemas_pydantic.replay_schemas import ExecutionResultSummary


@dataclass
class ReplaySessionStatusDetail(ReplaySessionState):
    """Status detail with computed metadata for admin API."""

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

    def __post_init__(self) -> None:
        raw: Any = self.filter
        if isinstance(raw, dict):
            self.filter = ReplayFilter(**raw)
