from dataclasses import field
from datetime import datetime

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from app.domain.enums import EventType
from app.domain.events.typed import DomainEvent, EventMetadata


@dataclass(config=ConfigDict(from_attributes=True))
class EventSummary:
    """Lightweight event summary for lists and previews."""

    event_id: str
    event_type: EventType
    timestamp: datetime
    aggregate_id: str | None = None


@dataclass(config=ConfigDict(from_attributes=True))
class EventFilter:
    """Filter criteria for querying events."""

    event_types: list[EventType] | None = None
    aggregate_id: str | None = None
    user_id: str | None = None
    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    search_text: str | None = None
    status: str | None = None


@dataclass(config=ConfigDict(from_attributes=True))
class EventListResult:
    """Result of event list query."""

    events: list[DomainEvent]
    total: int
    skip: int
    limit: int
    has_more: bool


@dataclass(config=ConfigDict(from_attributes=True))
class EventBrowseResult:
    """Result for event browsing."""

    events: list[DomainEvent]
    total: int
    skip: int
    limit: int


@dataclass(config=ConfigDict(from_attributes=True))
class EventDetail:
    """Detailed event information with related events."""

    event: DomainEvent
    related_events: list[EventSummary] = field(default_factory=list)
    timeline: list[EventSummary] = field(default_factory=list)


@dataclass(config=ConfigDict(from_attributes=True))
class EventTypeCount:
    event_type: EventType
    count: int


@dataclass(config=ConfigDict(from_attributes=True))
class HourlyEventCount:
    hour: str
    count: int


@dataclass(config=ConfigDict(from_attributes=True))
class ServiceEventCount:
    service_name: str
    count: int


@dataclass(config=ConfigDict(from_attributes=True))
class UserEventCount:
    user_id: str
    event_count: int


@dataclass(config=ConfigDict(from_attributes=True))
class EventStatistics:
    """Event statistics."""

    total_events: int
    events_by_type: list[EventTypeCount] = field(default_factory=list)
    events_by_service: list[ServiceEventCount] = field(default_factory=list)
    events_by_hour: list[HourlyEventCount] = field(default_factory=list)
    top_users: list[UserEventCount] = field(default_factory=list)
    error_rate: float = 0.0
    avg_processing_time: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None


@dataclass(config=ConfigDict(from_attributes=True))
class EventReplayInfo:
    """Information for event replay."""

    events: list[DomainEvent]
    event_count: int
    event_types: list[EventType]
    start_time: datetime
    end_time: datetime


@dataclass(config=ConfigDict(from_attributes=True))
class EventExportRow:
    """Event export row for CSV."""

    event_id: str
    event_type: EventType
    timestamp: datetime
    metadata: EventMetadata
    aggregate_id: str | None = None
