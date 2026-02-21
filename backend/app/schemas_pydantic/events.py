from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import EventType
from app.domain.events import DomainEvent
from app.domain.events.event_models import (
    EventBrowseResult,
    EventDetail,
    EventExportRow,
    EventFilter,
    EventListResult,
    EventReplayInfo,
    EventSummary,
    EventTypeCount,
    HourlyEventCount,
    ServiceEventCount,
    UserEventCount,
)


class EventStatistics(BaseModel):
    """Event statistics with API schema extras."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
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

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    name: str
    pipeline: list[dict[str, Any]]
    output_collection: str
    description: str | None = None
    source_events: list[EventType] | None = None
    refresh_interval_seconds: int = 300
    last_updated: datetime | None = None


class ExecutionEventsResult(BaseModel):
    """Result of execution events query."""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    events: list[DomainEvent]
    access_allowed: bool
    include_system_events: bool


__all__ = [
    "EventSummary",
    "EventFilter",
    "EventListResult",
    "EventBrowseResult",
    "EventDetail",
    "EventTypeCount",
    "HourlyEventCount",
    "ServiceEventCount",
    "UserEventCount",
    "EventStatistics",
    "EventReplayInfo",
    "EventExportRow",
    "EventProjection",
    "ExecutionEventsResult",
]
