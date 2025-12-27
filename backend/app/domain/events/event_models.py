from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.utils import StringEnum
from app.domain.enums.events import EventType
from app.domain.events.event_metadata import EventMetadata

MongoQueryValue = str | dict[str, str | list[str] | float | datetime]
MongoQuery = dict[str, MongoQueryValue]


class EventFields(StringEnum):
    """Database field names for events collection."""

    ID = "_id"
    EVENT_ID = "event_id"
    EVENT_TYPE = "event_type"
    EVENT_VERSION = "event_version"
    TIMESTAMP = "timestamp"
    AGGREGATE_ID = "aggregate_id"
    METADATA = "metadata"
    PAYLOAD = "payload"
    STORED_AT = "stored_at"
    TTL_EXPIRES_AT = "ttl_expires_at"
    STATUS = "status"
    ERROR = "error"

    # Metadata sub-fields
    METADATA_CORRELATION_ID = "metadata.correlation_id"
    METADATA_USER_ID = "metadata.user_id"
    METADATA_SERVICE_NAME = "metadata.service_name"
    METADATA_SERVICE_VERSION = "metadata.service_version"
    METADATA_IP_ADDRESS = "metadata.ip_address"
    METADATA_USER_AGENT = "metadata.user_agent"

    # Payload sub-fields for common queries
    PAYLOAD_EXECUTION_ID = "payload.execution_id"
    PAYLOAD_POD_NAME = "payload.pod_name"
    PAYLOAD_DURATION_SECONDS = "payload.duration_seconds"

    # Archive fields
    DELETED_AT = "_deleted_at"
    DELETED_BY = "_deleted_by"
    DELETION_REASON = "_deletion_reason"


class EventSortOrder(StringEnum):
    ASC = "asc"
    DESC = "desc"


class SortDirection:
    ASCENDING = 1
    DESCENDING = -1


class CollectionNames(StringEnum):
    EVENTS = "events"
    EVENT_STORE = "event_store"
    REPLAY_SESSIONS = "replay_sessions"
    EVENTS_ARCHIVE = "events_archive"
    RESOURCE_ALLOCATIONS = "resource_allocations"
    USERS = "users"
    EXECUTIONS = "executions"
    EXECUTION_RESULTS = "execution_results"
    SAVED_SCRIPTS = "saved_scripts"
    NOTIFICATIONS = "notifications"
    NOTIFICATION_SUBSCRIPTIONS = "notification_subscriptions"
    USER_SETTINGS = "user_settings"
    USER_SETTINGS_SNAPSHOTS = "user_settings_snapshots"
    SAGAS = "sagas"
    DLQ_MESSAGES = "dlq_messages"


@dataclass
class Event:
    """Domain model for an event."""

    event_id: str
    event_type: EventType
    event_version: str
    timestamp: datetime
    metadata: EventMetadata
    payload: dict[str, Any]
    aggregate_id: str | None = None
    stored_at: datetime | None = None
    ttl_expires_at: datetime | None = None
    status: str | None = None
    error: str | None = None

    @property
    def correlation_id(self) -> str | None:
        return self.metadata.correlation_id


@dataclass
class EventSummary:
    """Lightweight event summary for lists and previews."""

    event_id: str
    event_type: str
    timestamp: datetime
    aggregate_id: str | None = None


@dataclass
class EventFilter:
    """Filter criteria for querying events."""

    event_types: list[str] | None = None
    aggregate_id: str | None = None
    correlation_id: str | None = None
    user_id: str | None = None
    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    search_text: str | None = None
    text_search: str | None = None
    status: str | None = None


@dataclass
class EventQuery:
    """Query parameters for event search."""

    filter: EventFilter
    sort_by: str = EventFields.TIMESTAMP
    sort_order: EventSortOrder = EventSortOrder.DESC
    limit: int = 100
    skip: int = 0

    def get_sort_direction(self) -> int:
        return SortDirection.DESCENDING if self.sort_order == EventSortOrder.DESC else SortDirection.ASCENDING


@dataclass
class EventListResult:
    """Result of event list query."""

    events: list[Event]
    total: int
    skip: int
    limit: int
    has_more: bool


@dataclass
class EventBrowseResult:
    """Result for event browsing."""

    events: list[Event]
    total: int
    skip: int
    limit: int


@dataclass
class EventDetail:
    """Detailed event information with related events."""

    event: Event
    related_events: list[EventSummary] = field(default_factory=list)
    timeline: list[EventSummary] = field(default_factory=list)


@dataclass
class HourlyEventCount:
    hour: str
    count: int


@dataclass
class UserEventCount:
    user_id: str
    event_count: int


@dataclass
class EventStatistics:
    """Event statistics."""

    total_events: int
    events_by_type: dict[str, int] = field(default_factory=dict)
    events_by_service: dict[str, int] = field(default_factory=dict)
    events_by_hour: list[HourlyEventCount | dict[str, Any]] = field(default_factory=list)
    top_users: list[UserEventCount] = field(default_factory=list)
    error_rate: float = 0.0
    avg_processing_time: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None


@dataclass
class EventProjection:
    """Configuration for event projections."""

    name: str
    pipeline: list[dict[str, Any]]
    output_collection: str
    description: str | None = None
    source_events: list[str] | None = None
    refresh_interval_seconds: int = 300
    last_updated: datetime | None = None


@dataclass
class ArchivedEvent(Event):
    """Archived event with deletion metadata."""

    deleted_at: datetime | None = None
    deleted_by: str | None = None
    deletion_reason: str | None = None


@dataclass
class EventReplayInfo:
    """Information for event replay."""

    events: list[Event]
    event_count: int
    event_types: list[str]
    start_time: datetime
    end_time: datetime


@dataclass
class ExecutionEventsResult:
    """Result of execution events query."""

    events: list[Event]
    access_allowed: bool
    include_system_events: bool

    def get_filtered_events(self) -> list[Event]:
        """Get events filtered based on access and system event settings."""
        if not self.access_allowed:
            return []

        events = self.events
        if not self.include_system_events:
            events = [e for e in events if not e.metadata.service_name.startswith("system-")]

        return events


@dataclass
class EventExportRow:
    """Event export row for CSV."""

    event_id: str
    event_type: str
    timestamp: str
    correlation_id: str
    aggregate_id: str
    user_id: str
    service: str
    status: str
    error: str


@dataclass
class EventAggregationResult:
    """Result of event aggregation."""

    results: list[dict[str, Any]]
    pipeline: list[dict[str, Any]]
    execution_time_ms: float | None = None
