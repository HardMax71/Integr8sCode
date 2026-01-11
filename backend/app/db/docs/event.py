from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pymongo
from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.domain.enums.events import EventType
from app.domain.events.typed import EventMetadata


class EventDocument(Document):
    """Event document for event browsing/admin system.

    Uses extra='allow' for flexible event data storage - event-specific fields
    are stored directly at document level (no payload wrapper needed).
    """

    event_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    event_type: EventType  # Indexed via Settings.indexes
    event_version: str = "1.0"
    timestamp: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    aggregate_id: Indexed(str) | None = None  # type: ignore[valid-type]
    metadata: EventMetadata
    stored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30))

    # Most event types have execution_id (sparse-indexed)
    execution_id: str | None = None

    model_config = ConfigDict(from_attributes=True, extra="allow")

    class Settings:
        name = "events"
        use_state_management = True
        indexes = [
            # Compound indexes for common query patterns
            IndexModel([("event_type", ASCENDING), ("timestamp", DESCENDING)], name="idx_event_type_ts"),
            IndexModel([("aggregate_id", ASCENDING), ("timestamp", DESCENDING)], name="idx_aggregate_ts"),
            IndexModel([("metadata.correlation_id", ASCENDING)], name="idx_meta_correlation"),
            IndexModel([("metadata.user_id", ASCENDING), ("timestamp", DESCENDING)], name="idx_meta_user_ts"),
            IndexModel([("metadata.service_name", ASCENDING), ("timestamp", DESCENDING)], name="idx_meta_service_ts"),
            # Event-specific field indexes (sparse - only exist on relevant event types)
            IndexModel([("execution_id", ASCENDING)], name="idx_execution_id", sparse=True),
            IndexModel([("pod_name", ASCENDING)], name="idx_pod_name", sparse=True),
            # TTL index (expireAfterSeconds=0 means use ttl_expires_at value directly)
            IndexModel([("ttl_expires_at", ASCENDING)], name="idx_ttl", expireAfterSeconds=0),
            # Additional compound indexes for query optimization
            IndexModel([("event_type", ASCENDING), ("aggregate_id", ASCENDING)], name="idx_events_type_agg"),
            IndexModel([("aggregate_id", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_agg_ts"),
            IndexModel([("event_type", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_type_ts_asc"),
            IndexModel([("metadata.user_id", ASCENDING), ("timestamp", ASCENDING)], name="idx_events_user_ts"),
            IndexModel([("metadata.user_id", ASCENDING), ("event_type", ASCENDING)], name="idx_events_user_type"),
            IndexModel(
                [("event_type", ASCENDING), ("metadata.user_id", ASCENDING), ("timestamp", DESCENDING)],
                name="idx_events_type_user_ts",
            ),
            # Text search index
            IndexModel(
                [
                    ("event_type", pymongo.TEXT),
                    ("metadata.service_name", pymongo.TEXT),
                    ("metadata.user_id", pymongo.TEXT),
                    ("execution_id", pymongo.TEXT),
                ],
                name="idx_text_search",
                language_override="none",
                default_language="english",
            ),
        ]


class EventArchiveDocument(Document):
    """Archived event with deletion metadata.

    Mirrors EventDocument structure with additional archive metadata.
    Uses extra='allow' for event-specific fields.
    """

    event_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    event_type: EventType  # Indexed via Settings.indexes
    event_version: str = "1.0"
    timestamp: Indexed(datetime)  # type: ignore[valid-type]
    aggregate_id: str | None = None
    metadata: EventMetadata
    stored_at: datetime | None = None
    ttl_expires_at: datetime | None = None

    # Archive metadata
    deleted_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    deleted_by: str | None = None
    deletion_reason: str | None = None

    model_config = ConfigDict(from_attributes=True, extra="allow")

    class Settings:
        name = "events_archive"
        use_state_management = True
        indexes = [
            IndexModel([("event_type", 1)]),
        ]
