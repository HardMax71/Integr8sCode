from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.enums import EventType, KafkaTopic, ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay.models import ReplayError, ReplayFilter


class ReplayFilterSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str | None = None
    event_types: list[EventType] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: str | None = None
    service_name: str | None = None
    exclude_event_types: list[EventType] | None = None


class ReplayConfigSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilterSchema = Field(default_factory=ReplayFilterSchema)

    speed_multiplier: float = Field(default=1.0, ge=0.1, le=100.0)
    preserve_timestamps: bool = False
    batch_size: int = Field(default=100, ge=1, le=1000)
    max_events: int | None = Field(default=None, ge=1)

    target_topics: dict[EventType, KafkaTopic] | None = None
    target_file_path: str | None = None

    skip_errors: bool = True
    retry_failed: bool = False
    retry_attempts: int = 3

    enable_progress_tracking: bool = True


class ReplaySession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    config: ReplayConfigSchema
    status: ReplayStatus = ReplayStatus.CREATED

    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None

    errors: list[ReplayError] = Field(default_factory=list)


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


class CleanupResponse(BaseModel):
    """Response schema for cleanup operations"""

    model_config = ConfigDict(from_attributes=True)

    removed_sessions: int
    message: str
