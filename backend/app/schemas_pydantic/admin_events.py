from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums.events import EventType
from app.domain.events.event_models import EventSummary
from app.domain.events.typed import DomainEvent
from app.domain.replay import ReplayError
from app.schemas_pydantic.events import EventTypeCountSchema, HourlyEventCountSchema
from app.schemas_pydantic.execution import ExecutionResult


class EventFilter(BaseModel):
    """Filter criteria for browsing events"""

    event_types: list[EventType] | None = None
    aggregate_id: str | None = None
    correlation_id: str | None = None
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
    sort_by: str = "timestamp"
    sort_order: int = -1


class EventReplayRequest(BaseModel):
    """Request model for replaying events"""

    event_ids: list[str] | None = None
    correlation_id: str | None = None
    aggregate_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    target_service: str | None = None
    dry_run: bool = True


class EventBrowseResponse(BaseModel):
    """Response model for browsing events"""

    events: list[DomainEvent]
    total: int
    skip: int
    limit: int


class EventDetailResponse(BaseModel):
    """Response model for event detail"""

    event: DomainEvent
    related_events: list[EventSummary]
    timeline: list[EventSummary]


class EventReplayResponse(BaseModel):
    """Response model for event replay"""

    dry_run: bool
    total_events: int
    replay_correlation_id: str
    session_id: str | None = None
    status: str
    events_preview: list[EventSummary] | None = None


class EventReplayStatusResponse(BaseModel):
    """Response model for replay status"""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    status: str
    total_events: int
    replayed_events: int
    failed_events: int
    skipped_events: int
    correlation_id: str
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

    message: str
    event_id: str


class UserEventCountSchema(BaseModel):
    """User event count schema"""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    event_count: int


class EventStatsResponse(BaseModel):
    """Response model for event statistics"""

    model_config = ConfigDict(from_attributes=True)

    total_events: int
    events_by_type: list[EventTypeCountSchema]
    events_by_hour: list[HourlyEventCountSchema]
    top_users: list[UserEventCountSchema]
    error_rate: float
    avg_processing_time: float
