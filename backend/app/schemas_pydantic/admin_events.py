"""Admin events schemas"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventFilter(BaseModel):
    """Filter criteria for browsing events"""
    event_types: Optional[List[str]] = None
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    service_name: Optional[str] = None
    search_text: Optional[str] = None


class EventBrowseRequest(BaseModel):
    """Request model for browsing events"""
    filters: EventFilter
    skip: int = 0
    limit: int = Field(default=50, le=500)
    sort_by: str = "timestamp"
    sort_order: int = -1


class EventReplayRequest(BaseModel):
    """Request model for replaying events"""
    event_ids: Optional[List[str]] = None
    correlation_id: Optional[str] = None
    aggregate_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    target_service: Optional[str] = None
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
    session_id: Optional[str] = None
    status: str
    events_preview: Optional[List[Dict[str, Any]]] = None


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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    progress_percentage: float
    estimated_completion: Optional[datetime] = None


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
