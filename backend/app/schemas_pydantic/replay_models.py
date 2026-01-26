from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.replay import ReplayStatus, ReplayTarget, ReplayType
from app.domain.replay import ReplayError


class ReplayFilterSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str | None = None
    event_types: list[EventType] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    user_id: str | None = None
    service_name: str | None = None
    custom_query: dict[str, Any] | None = None
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
