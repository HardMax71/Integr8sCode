from datetime import datetime, timezone
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, ConfigDict, Field
from pymongo import IndexModel

from app.domain.enums import EventType, KafkaTopic, ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayError, ReplayFilter


class ReplayConfig(BaseModel):
    """Replay configuration (embedded document).

    Copied from domain/replay/models.py ReplayConfig.
    """

    replay_type: ReplayType
    target: ReplayTarget = ReplayTarget.KAFKA
    filter: ReplayFilter = Field(default_factory=ReplayFilter)

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

    model_config = ConfigDict(from_attributes=True)


class ReplaySessionDocument(Document):
    """Domain replay session model stored in database.

    Single source of truth for replay sessions. Used by both
    ReplayService and AdminEventsRepository.
    """

    session_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    config: ReplayConfig
    status: ReplayStatus = ReplayStatus.CREATED  # Indexed via Settings.indexes

    total_events: int = 0
    replayed_events: int = 0
    failed_events: int = 0
    skipped_events: int = 0

    created_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_event_at: datetime | None = None

    errors: list[ReplayError] = Field(default_factory=list)

    # Tracking and admin fields
    replay_id: str = Field(default_factory=lambda: str(uuid4()))
    created_by: str | None = None
    target_service: str | None = None
    dry_run: bool = False
    triggered_executions: list[str] = Field(default_factory=list)
    error: str | None = None  # Single error message for admin display

    model_config = ConfigDict(from_attributes=True)

    @property
    def is_running(self) -> bool:
        """Check if session is running."""
        return self.status == ReplayStatus.RUNNING

    class Settings:
        name = "replay_sessions"
        use_state_management = True
        indexes = [
            IndexModel([("status", 1)]),
            IndexModel([("replay_id", 1)]),
        ]
