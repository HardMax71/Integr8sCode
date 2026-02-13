from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import ReplayStatus


class ReplaySessionUpdate(BaseModel):
    """Domain model for replay session updates."""

    model_config = ConfigDict(from_attributes=True)

    status: ReplayStatus | None = None
    total_events: int | None = None
    replayed_events: int | None = None
    failed_events: int | None = None
    skipped_events: int | None = None
    replay_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    target_service: str | None = None
    dry_run: bool | None = None
