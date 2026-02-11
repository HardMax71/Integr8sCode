from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import EventType


class EventTypeCountSchema(BaseModel):
    """Event count by type."""

    model_config = ConfigDict(from_attributes=True)

    event_type: EventType
    count: int


class HourlyEventCountSchema(BaseModel):
    """Hourly event count for statistics."""

    model_config = ConfigDict(from_attributes=True)

    hour: str
    count: int


class ServiceEventCountSchema(BaseModel):
    """Event count by service."""

    model_config = ConfigDict(from_attributes=True)

    service_name: str
    count: int


class EventStatistics(BaseModel):
    """Event statistics response."""

    total_events: int
    events_by_type: list[EventTypeCountSchema]
    events_by_service: list[ServiceEventCountSchema]
    events_by_hour: list[HourlyEventCountSchema]
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
