"""Replay schemas for event replay functionality"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas_avro.event_schemas import EventType
from app.services.event_replay import ReplayStatus, ReplayTarget, ReplayType


class ReplayRequest(BaseModel):
    """Request schema for creating replay sessions"""
    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA

    # Filter options
    execution_id: Optional[str] = None
    event_types: Optional[List[EventType]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    user_id: Optional[str] = None
    service_name: Optional[str] = None

    # Replay configuration
    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: Optional[int] = Field(default=None, ge=1)
    skip_errors: bool = True
    target_file_path: Optional[str] = None


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
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float] = None
    throughput_events_per_second: Optional[float] = None


class CleanupResponse(BaseModel):
    """Response schema for cleanup operations"""
    removed_sessions: int
    message: str
