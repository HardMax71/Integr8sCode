from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums import EventType, ExecutionErrorType, ExecutionStatus, ReplayStatus
from app.domain.events import DomainEvent, ResourceUsageDomain
from app.domain.replay import ReplayError
from app.schemas_pydantic.events import EventSummary, EventTypeCount, HourlyEventCount, UserEventCount
from app.schemas_pydantic.execution import ExecutionResult


class EventFilter(BaseModel):
    """Filter criteria for browsing events"""

    event_types: list[EventType] | None = None
    aggregate_id: str | None = None
    user_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    service_name: str | None = None
    search_text: str | None = None


class EventBrowseRequest(BaseModel):
    """Request model for browsing events"""

    filters: EventFilter
    skip: int = 0
    limit: int = Field(default=50, le=500)


class EventReplayRequest(BaseModel):
    """Request model for replaying events"""

    event_ids: list[str] | None = None
    aggregate_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    target_service: str | None = None
    dry_run: bool = True


class EventBrowseResponse(BaseModel):
    """Response model for browsing events"""

    model_config = ConfigDict(from_attributes=True)

    events: list[DomainEvent]
    total: int
    skip: int
    limit: int


class EventDetailResponse(BaseModel):
    """Response model for event detail"""

    model_config = ConfigDict(from_attributes=True)

    event: DomainEvent
    related_events: list[EventSummary]
    timeline: list[EventSummary]


class EventReplayResponse(BaseModel):
    """Response model for event replay"""

    model_config = ConfigDict(from_attributes=True)

    dry_run: bool
    total_events: int
    replay_id: str
    session_id: str | None = None
    status: ReplayStatus
    events_preview: list[EventSummary] | None = None


class EventReplayStatusResponse(BaseModel):
    """Response model for replay status"""

    model_config = ConfigDict(from_attributes=True)

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
    errors: list[ReplayError] | None = None
    estimated_completion: datetime | None = None
    execution_results: list[ExecutionResult] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_percentage(self) -> float:
        return round(self.replayed_events / max(self.total_events, 1) * 100, 2)


class EventDeleteResponse(BaseModel):
    """Response model for event deletion"""

    model_config = ConfigDict(from_attributes=True)

    message: str
    event_id: str


class EventStatsResponse(BaseModel):
    """Response model for event statistics"""

    model_config = ConfigDict(from_attributes=True)

    total_events: int
    events_by_type: list[EventTypeCount]
    events_by_hour: list[HourlyEventCount]
    top_users: list[UserEventCount]
    error_rate: float
    avg_processing_time: float


class ExecutionResultSummary(BaseModel):
    """Summary of an execution result for replay status."""

    model_config = ConfigDict(from_attributes=True)

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
