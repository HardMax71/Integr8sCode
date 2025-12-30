from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums.events import EventType
from app.schemas_pydantic.events import HourlyEventCountSchema
from app.schemas_pydantic.execution import ExecutionResult


class ReplayErrorInfo(BaseModel):
    """Error info for replay operations."""

    timestamp: datetime
    error: str
    event_id: str | None = None
    error_type: str | None = None


class EventFilter(BaseModel):
    """Filter criteria for browsing events"""

    event_types: List[EventType] | None = None
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

    event_ids: List[str] | None = None
    correlation_id: str | None = None
    aggregate_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    target_service: str | None = None
    dry_run: bool = True


class EventBrowseResponse(BaseModel):
    """Response model for browsing events"""

    events: List[Dict[str, Any]]
    total: int
    skip: int
    limit: int


class EventDetailResponse(BaseModel):
    """Response model for event detail"""

    event: Dict[str, Any]
    related_events: List[Dict[str, Any]]
    timeline: List[Dict[str, Any]]


class EventReplayResponse(BaseModel):
    """Response model for event replay"""

    dry_run: bool
    total_events: int
    replay_correlation_id: str
    session_id: str | None = None
    status: str
    events_preview: List[Dict[str, Any]] | None = None


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
    errors: List[ReplayErrorInfo] | None = None
    estimated_completion: datetime | None = None
    execution_results: List[ExecutionResult] | None = None

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
    events_by_type: Dict[str, int]
    events_by_hour: List[HourlyEventCountSchema]
    top_users: List[UserEventCountSchema]
    error_rate: float
    avg_processing_time: float
