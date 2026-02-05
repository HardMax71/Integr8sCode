from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.dlq.models import DLQMessageStatus
from app.domain.events.typed import BaseEvent


class DLQMessageDocument(Document):
    """Unified DLQ message document. Access event_id via event.event_id."""

    model_config = ConfigDict(from_attributes=True)

    event: BaseEvent
    original_topic: Indexed(str) = ""  # type: ignore[valid-type]
    error: str = "Unknown error"
    retry_count: Indexed(int) = 0  # type: ignore[valid-type]
    failed_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    status: DLQMessageStatus = DLQMessageStatus.PENDING
    producer_id: str = "unknown"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime | None = None
    next_retry_at: Indexed(datetime) | None = None  # type: ignore[valid-type]
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    class Settings:
        name = "dlq_messages"
        use_state_management = True
        indexes = [
            IndexModel([("event.event_id", ASCENDING)], unique=True, name="idx_dlq_event_id"),
            IndexModel([("original_topic", ASCENDING)], name="idx_dlq_original_topic"),
            IndexModel([("status", ASCENDING)], name="idx_dlq_status"),
            IndexModel([("failed_at", DESCENDING)], name="idx_dlq_failed_desc"),
            IndexModel([("created_at", ASCENDING)], name="idx_dlq_created_ttl", expireAfterSeconds=7 * 24 * 3600),
        ]
