from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from app.core.utils import StringEnum
from app.domain.enums.replay import ReplayStatus
from app.domain.events.event_models import EventSummary


class ReplaySessionFields(StringEnum):
    """Database field names for replay sessions."""

    SESSION_ID = "session_id"
    TYPE = "type"
    STATUS = "status"
    TOTAL_EVENTS = "total_events"
    REPLAYED_EVENTS = "replayed_events"
    FAILED_EVENTS = "failed_events"
    SKIPPED_EVENTS = "skipped_events"
    CORRELATION_ID = "correlation_id"
    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    COMPLETED_AT = "completed_at"
    ERROR = "error"
    CREATED_BY = "created_by"
    TARGET_SERVICE = "target_service"
    DRY_RUN = "dry_run"


@dataclass
class ReplaySession:
    session_id: str
    status: ReplayStatus
    total_events: int
    correlation_id: str
    created_at: datetime
    type: str = "replay_session"
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    created_by: str | None = None
    target_service: str | None = None
    dry_run: bool = False
    triggered_executions: list[str] = field(default_factory=list)  # Track execution IDs created by replay

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_events == 0:
            return 0.0
        return round((self.replayed_events / self.total_events) * 100, 2)

    @property
    def is_completed(self) -> bool:
        """Check if session is completed."""
        return self.status in [ReplayStatus.COMPLETED, ReplayStatus.FAILED, ReplayStatus.CANCELLED]

    @property
    def is_running(self) -> bool:
        """Check if session is running."""
        return self.status == ReplayStatus.RUNNING

    def update_progress(self, replayed: int, failed: int = 0, skipped: int = 0) -> "ReplaySession":
        # Create new instance with updated values
        new_session = replace(self, replayed_events=replayed, failed_events=failed, skipped_events=skipped)

        # Check if completed and update status
        if new_session.replayed_events >= new_session.total_events:
            new_session = replace(new_session, status=ReplayStatus.COMPLETED, completed_at=datetime.now(timezone.utc))

        return new_session


@dataclass
class ReplaySessionStatusDetail:
    session: ReplaySession
    estimated_completion: datetime | None = None
    execution_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReplaySessionStatusInfo:
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
    query: dict[str, Any]
    events_preview: list[EventSummary] = field(default_factory=list)
