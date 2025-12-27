from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.domain.enums.events import EventType
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType


class ReplayRequest(BaseModel):
    """Request schema for creating replay sessions"""

    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA

    # Filter options
    execution_id: str | None = None
    event_types: List[EventType] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: str | None = None
    service_name: str | None = None
    custom_query: Dict[str, Any] | None = None
    exclude_event_types: List[EventType] | None = None

    # Replay configuration
    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: int | None = Field(default=None, ge=1)
    skip_errors: bool = True
    target_file_path: str | None = None
    target_topics: Dict[str, str] | None = None
    retry_failed: bool = False
    retry_attempts: int = Field(default=3, ge=1, le=10)
    enable_progress_tracking: bool = True


class ReplayResponse(BaseModel):
    """Response schema for replay operations"""

    session_id: str
    status: ReplayStatus
    message: str


class SessionSummary(BaseModel):
    """Summary information for replay sessions"""

    session_id: str
    replay_type: ReplayType
    target: ReplayTarget
    status: ReplayStatus
    total_events: int
    replayed_events: int
    failed_events: int
    skipped_events: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None = None
    throughput_events_per_second: float | None = None


class CleanupResponse(BaseModel):
    """Response schema for cleanup operations"""

    removed_sessions: int
    message: str
