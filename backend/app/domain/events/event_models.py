from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import EventType
from app.domain.events.typed import DomainEvent, EventMetadata


@dataclass
class EventSummary:
    event_id: str
    event_type: EventType
    timestamp: datetime
    aggregate_id: str | None = None


@dataclass
class EventFilter:
    event_types: list[EventType] | None = None
    aggregate_id: str | None = None
    user_id: str | None = None
    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    search_text: str | None = None
    status: str | None = None


@dataclass
class EventListResult:
    events: list[DomainEvent]
    total: int
    skip: int
    limit: int
    has_more: bool


@dataclass
class EventBrowseResult:
    events: list[DomainEvent]
    total: int
    skip: int
    limit: int


@dataclass
class EventDetail:
    event: DomainEvent
    related_events: list[EventSummary] = field(default_factory=list)
    timeline: list[EventSummary] = field(default_factory=list)


@dataclass
class EventTypeCount:
    event_type: EventType
    count: int


@dataclass
class HourlyEventCount:
    hour: str
    count: int


@dataclass
class ServiceEventCount:
    service_name: str
    count: int


@dataclass
class UserEventCount:
    user_id: str
    event_count: int


@dataclass
class EventStatistics:
    total_events: int
    events_by_type: list[EventTypeCount] = field(default_factory=list)
    events_by_service: list[ServiceEventCount] = field(default_factory=list)
    events_by_hour: list[HourlyEventCount] = field(default_factory=list)
    top_users: list[UserEventCount] = field(default_factory=list)
    error_rate: float = 0.0
    avg_processing_time: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None


@dataclass
class EventReplayInfo:
    events: list[DomainEvent]
    event_count: int
    event_types: list[EventType]
    start_time: datetime
    end_time: datetime


@dataclass
class EventExportRow:
    event_id: str
    event_type: EventType
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadata | None = None
