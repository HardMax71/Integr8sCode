"""Domain models for replay session updates."""

from datetime import datetime

from pydantic.dataclasses import dataclass

from app.domain.enums.replay import ReplayStatus


@dataclass
class ReplaySessionUpdate:
    """Domain model for replay session updates."""

    status: ReplayStatus | None = None
    total_events: int | None = None
    replayed_events: int | None = None
    failed_events: int | None = None
    skipped_events: int | None = None
    correlation_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    target_service: str | None = None
    dry_run: bool | None = None
