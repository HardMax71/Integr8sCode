from __future__ import annotations

from datetime import datetime

from pydantic.dataclasses import dataclass

from app.core.utils import StringEnum


class IdempotencyStatus(StringEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class KeyStrategy(StringEnum):
    """Strategy for generating idempotency keys."""

    EVENT_BASED = "event_based"
    CONTENT_HASH = "content_hash"
    CUSTOM = "custom"


@dataclass
class IdempotencyRecord:
    key: str
    status: IdempotencyStatus
    event_type: str
    event_id: str
    created_at: datetime
    ttl_seconds: int
    completed_at: datetime | None = None
    processing_duration_ms: int | None = None
    error: str | None = None
    result_json: str | None = None
