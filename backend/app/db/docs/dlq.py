from datetime import datetime, timezone
from typing import Any

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.dlq.models import DLQMessageStatus
from app.domain.enums.events import EventType


class DLQMessageDocument(Document):
    """Unified DLQ message document for the entire system.

    Copied from DLQMessage dataclass.
    """

    # Core fields - always required
    event: dict[str, Any]  # The original event as dict (BaseEvent serialized)
    event_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    event_type: EventType  # Indexed via Settings.indexes
    original_topic: Indexed(str)  # type: ignore[valid-type]
    error: str  # Error message from the failure
    retry_count: Indexed(int)  # type: ignore[valid-type]
    failed_at: Indexed(datetime)  # type: ignore[valid-type]
    status: DLQMessageStatus  # Indexed via Settings.indexes
    producer_id: str  # ID of the producer that sent to DLQ

    # Optional fields
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime | None = None
    next_retry_at: Indexed(datetime) | None = None  # type: ignore[valid-type]
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None

    # Kafka message headers (optional)
    headers: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "dlq_messages"
        use_state_management = True
        indexes = [
            IndexModel([("event_type", ASCENDING)], name="idx_dlq_event_type"),
            IndexModel([("status", ASCENDING)], name="idx_dlq_status"),
            IndexModel([("failed_at", DESCENDING)], name="idx_dlq_failed_desc"),
            # TTL index - auto-delete after 7 days
            IndexModel([("created_at", ASCENDING)], name="idx_dlq_created_ttl", expireAfterSeconds=7 * 24 * 3600),
        ]

    @property
    def age_seconds(self) -> float:
        """Get message age in seconds since failure."""
        return (datetime.now(timezone.utc) - self.failed_at).total_seconds()
