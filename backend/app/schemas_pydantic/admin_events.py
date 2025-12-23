from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.domain.enums.events import EventType


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
    error: str | None = None
    progress_percentage: float
    estimated_completion: datetime | None = None
    execution_results: List[Dict[str, Any]] | None = None  # Results from replayed executions


class EventDeleteResponse(BaseModel):
    """Response model for event deletion"""

    message: str
    event_id: str


class EventStatsResponse(BaseModel):
    """Response model for event statistics"""

    total_events: int
    events_by_type: Dict[str, int]
    events_by_hour: List[Dict[str, Any]]
    top_users: List[Dict[str, Any]]
    error_rate: float
    avg_processing_time: float
