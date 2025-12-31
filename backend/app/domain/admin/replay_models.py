from dataclasses import field
from datetime import datetime
from typing import Any

from pydantic.dataclasses import dataclass

from app.domain.enums.replay import ReplayStatus
from app.domain.events.event_models import EventSummary
from app.domain.replay.models import ReplaySessionState


@dataclass
class ReplaySessionStatusDetail:
    """Status detail with computed metadata for admin API."""

    session: ReplaySessionState
    estimated_completion: datetime | None = None
    execution_results: list[dict[str, Any]] = field(default_factory=list)


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
class ReplayQuery:
    event_ids: list[str] | None = None
    correlation_id: str | None = None
    aggregate_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None

    def is_empty(self) -> bool:
        return not any([self.event_ids, self.correlation_id, self.aggregate_id, self.start_time, self.end_time])


@dataclass
class ReplaySessionData:
    """Unified replay session data for both preview and actual replay."""

    total_events: int
    replay_correlation_id: str
    dry_run: bool
    query: ReplayQuery
    events_preview: list[EventSummary] = field(default_factory=list)
