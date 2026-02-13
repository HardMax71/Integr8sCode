from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.utils import StringEnum
from app.domain.enums import EventType
from app.domain.events.typed import DomainEvent, EventMetadata

MongoQueryValue = str | dict[str, str | list[str] | float | datetime]
MongoQuery = dict[str, MongoQueryValue]


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


class EventSummary(BaseModel):
    """Lightweight event summary for lists and previews."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: EventType
    timestamp: datetime
    aggregate_id: str | None = None


class EventFilter(BaseModel):
    """Filter criteria for querying events."""

    model_config = ConfigDict(from_attributes=True)

    event_types: list[EventType] | None = None
    aggregate_id: str | None = None
    user_id: str | None = None
    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    search_text: str | None = None
    status: str | None = None


class EventListResult(BaseModel):
    """Result of event list query."""

    model_config = ConfigDict(from_attributes=True)

    events: list[DomainEvent]
    total: int
    skip: int
    limit: int
    has_more: bool


class EventBrowseResult(BaseModel):
    """Result for event browsing."""

    model_config = ConfigDict(from_attributes=True)

    events: list[DomainEvent]
    total: int
    skip: int
    limit: int


class EventDetail(BaseModel):
    """Detailed event information with related events."""

    model_config = ConfigDict(from_attributes=True)

    event: DomainEvent
    related_events: list[EventSummary] = Field(default_factory=list)
    timeline: list[EventSummary] = Field(default_factory=list)


class EventTypeCount(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: EventType
    count: int


class HourlyEventCount(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hour: str
    count: int


class ServiceEventCount(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_name: str
    count: int


class UserEventCount(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    event_count: int


class EventStatistics(BaseModel):
    """Event statistics."""

    model_config = ConfigDict(from_attributes=True)

    total_events: int
    events_by_type: list[EventTypeCount] = Field(default_factory=list)
    events_by_service: list[ServiceEventCount] = Field(default_factory=list)
    events_by_hour: list[HourlyEventCount] = Field(default_factory=list)
    top_users: list[UserEventCount] = Field(default_factory=list)
    error_rate: float = 0.0
    avg_processing_time: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None


class EventProjection(BaseModel):
    """Configuration for event projections."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    pipeline: list[dict[str, Any]]
    output_collection: str
    description: str | None = None
    source_events: list[EventType] | None = None
    refresh_interval_seconds: int = 300
    last_updated: datetime | None = None


class EventReplayInfo(BaseModel):
    """Information for event replay."""

    model_config = ConfigDict(from_attributes=True)

    events: list[DomainEvent]
    event_count: int
    event_types: list[EventType]
    start_time: datetime
    end_time: datetime


class ExecutionEventsResult(BaseModel):
    """Result of execution events query."""

    model_config = ConfigDict(from_attributes=True)

    events: list[DomainEvent]
    access_allowed: bool
    include_system_events: bool

    def get_filtered_events(self) -> list[DomainEvent]:
        """Get events filtered based on access and system event settings."""
        if not self.access_allowed:
            return []

        events = self.events
        if not self.include_system_events:
            events = [e for e in events if not e.metadata.service_name.startswith("system-")]

        return events


class EventExportRow(BaseModel):
    """Event export row for CSV."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: EventType
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadata
