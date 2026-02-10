from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums import EventType, KafkaTopic, ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayFilter


class ReplayRequest(BaseModel):
    """Request schema for creating replay sessions"""

    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilter = Field(default_factory=ReplayFilter)

    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: int | None = Field(default=None, ge=1)
    skip_errors: bool = True
    target_file_path: str | None = None
    target_topics: dict[EventType, KafkaTopic] | None = None
    retry_failed: bool = False
    retry_attempts: int = Field(default=3, ge=1, le=10)
    enable_progress_tracking: bool = True


class ReplayResponse(BaseModel):
    """Response schema for replay operations"""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    status: ReplayStatus
    message: str


class SessionConfigSummary(BaseModel):
    """Lightweight config included in session listings."""

    model_config = ConfigDict(from_attributes=True)

    replay_type: ReplayType
    target: ReplayTarget


class SessionSummary(BaseModel):
    """Summary information for replay sessions"""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    config: SessionConfigSummary
    status: ReplayStatus
    total_events: int
    replayed_events: int
    failed_events: int
    skipped_events: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def throughput_events_per_second(self) -> float | None:
        if self.duration_seconds and self.duration_seconds > 0 and self.replayed_events > 0:
            return self.replayed_events / self.duration_seconds
        return None


class CleanupResponse(BaseModel):
    """Response schema for cleanup operations"""

    model_config = ConfigDict(from_attributes=True)

    removed_sessions: int
    message: str
