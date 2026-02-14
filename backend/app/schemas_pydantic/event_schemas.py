from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EventType
from app.domain.events.typed import DomainEvent, EventMetadata


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
    """Event statistics response."""

    total_events: int
    events_by_type: list[EventTypeCount] = Field(default_factory=list)
    events_by_service: list[ServiceEventCount] = Field(default_factory=list)
    events_by_hour: list[HourlyEventCount] = Field(default_factory=list)
    top_users: list[UserEventCount] = Field(default_factory=list)
    error_rate: float = 0.0
    avg_processing_time: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "total_events": 1543,
                "events_by_type": [
                    {"event_type": "EXECUTION_REQUESTED", "count": 523},
                    {"event_type": "EXECUTION_COMPLETED", "count": 498},
                    {"event_type": "POD_CREATED", "count": 522},
                ],
                "events_by_service": [
                    {"service_name": "api-gateway", "count": 523},
                    {"service_name": "execution-service", "count": 1020},
                ],
                "events_by_hour": [
                    {"hour": "2024-01-20 10:00", "count": 85},
                    {"hour": "2024-01-20 11:00", "count": 92},
                ],
            }
        },
    )


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


class EventExportRow(BaseModel):
    """Event export row for CSV."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: EventType
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadata
