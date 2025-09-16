"""Domain models for replay session updates."""

from dataclasses import dataclass
from datetime import datetime

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

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary, excluding None values."""
        result: dict[str, object] = {}

        if self.status is not None:
            result["status"] = self.status.value if hasattr(self.status, 'value') else self.status
        if self.total_events is not None:
            result["total_events"] = self.total_events
        if self.replayed_events is not None:
            result["replayed_events"] = self.replayed_events
        if self.failed_events is not None:
            result["failed_events"] = self.failed_events
        if self.skipped_events is not None:
            result["skipped_events"] = self.skipped_events
        if self.correlation_id is not None:
            result["correlation_id"] = self.correlation_id
        if self.started_at is not None:
            result["started_at"] = self.started_at
        if self.completed_at is not None:
            result["completed_at"] = self.completed_at
        if self.error is not None:
            result["error"] = self.error
        if self.target_service is not None:
            result["target_service"] = self.target_service
        if self.dry_run is not None:
            result["dry_run"] = self.dry_run

        return result

    def has_updates(self) -> bool:
        """Check if there are any updates to apply."""
        return bool(self.to_dict())
