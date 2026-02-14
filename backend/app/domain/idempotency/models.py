from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.utils import StringEnum
from app.domain.enums import EventType


class IdempotencyStatus(StringEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class KeyStrategy(StringEnum):
    """Strategy for generating idempotency keys."""

    EVENT_BASED = "event_based"
    CONTENT_HASH = "content_hash"
    CUSTOM = "custom"


@dataclass
class IdempotencyRecord:
    key: str
    status: IdempotencyStatus
    event_type: EventType
    event_id: str
    created_at: datetime
    ttl_seconds: int
    completed_at: datetime | None = None
    processing_duration_ms: int | None = None
    error: str | None = None
    result_json: str | None = None
