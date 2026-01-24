from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums.common import Environment, SortOrder
from app.domain.enums.events import EventType


class HourlyEventCountSchema(BaseModel):
    """Hourly event count for statistics."""

    model_config = ConfigDict(from_attributes=True)

    hour: str
    count: int


class EventMetadataResponse(BaseModel):
    """Pydantic schema for event metadata in API responses."""

    model_config = ConfigDict(from_attributes=True)

    service_name: str
    service_version: str
    correlation_id: str
    user_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    environment: Environment = Environment.PRODUCTION


class EventResponse(BaseModel):
    """API response schema for events. Captures all event-specific fields via extra='allow'."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    event_id: str
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime
    aggregate_id: str | None = None
    metadata: EventMetadataResponse


class EventListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    events: List[EventResponse]
    total: int
    limit: int
    skip: int
    has_more: bool


class EventFilterRequest(BaseModel):
    """Request model for filtering events."""

    event_types: List[EventType] | None = Field(None, description="Filter by event types")
    aggregate_id: str | None = Field(None, description="Filter by aggregate ID")
    correlation_id: str | None = Field(None, description="Filter by correlation ID")
    user_id: str | None = Field(None, description="Filter by user ID (admin only)")
    service_name: str | None = Field(None, description="Filter by service name")
    start_time: datetime | None = Field(None, description="Filter events after this time")
    end_time: datetime | None = Field(None, description="Filter events before this time")
    search_text: str | None = Field(None, description="Full-text search in event data")
    sort_by: str = Field("timestamp", description="Field to sort by")
    sort_order: SortOrder = Field(SortOrder.DESC, description="Sort order")
    limit: int = Field(100, ge=1, le=1000, description="Maximum events to return")
    skip: int = Field(0, ge=0, description="Number of events to skip")

    @field_validator("sort_by")
    @classmethod
    def validate_sort_field(cls, v: str) -> str:
        allowed_fields = {"timestamp", "event_type", "aggregate_id", "correlation_id", "stored_at"}
        if v not in allowed_fields:
            raise ValueError(f"Sort field must be one of {allowed_fields}")
        return v


class EventAggregationRequest(BaseModel):
    """Request model for event aggregation queries."""

    pipeline: List[Dict[str, Any]] = Field(..., description="MongoDB aggregation pipeline")
    limit: int = Field(100, ge=1, le=1000)


class PublishEventRequest(BaseModel):
    """Request model for publishing events."""

    event_type: EventType = Field(..., description="Type of event to publish")
    payload: Dict[str, Any] = Field(..., description="Event payload data")
    aggregate_id: str | None = Field(None, description="Aggregate root ID")
    correlation_id: str | None = Field(None, description="Correlation ID")
    causation_id: str | None = Field(None, description="ID of causing event")
    metadata: Dict[str, Any] | None = Field(None, description="Additional metadata")


class EventBase(BaseModel):
    """Base event model for API responses."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    event_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    aggregate_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None  # ID of the event that caused this event
    metadata: EventMetadataResponse
    payload: Dict[str, Any]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "event_type": EventType.EXECUTION_REQUESTED,
                "event_version": "1.0",
                "timestamp": "2024-01-20T10:30:00Z",
                "aggregate_id": "execution-123",
                "correlation_id": "request-456",
                "metadata": {
                    "user_id": "user-789",
                    "service_name": "api-gateway",
                    "service_version": "1.0.0",
                    "ip_address": "192.168.1.1",
                },
                "payload": {
                    "execution_id": "execution-123",
                    "script": "print('hello')",
                    "language": "python",
                    "version": "3.11",
                },
            }
        }
    )


class ExecutionEventPayload(BaseModel):
    """Common payload for execution-related events in API responses."""

    execution_id: str
    user_id: str
    status: str | None = None
    script: str | None = None
    language: str | None = None
    language_version: str | None = None
    output: str | None = None
    errors: str | None = None
    exit_code: int | None = None
    duration_seconds: float | None = None


class PodEventPayload(BaseModel):
    """Common payload for pod-related events in API responses."""

    pod_name: str
    namespace: str
    execution_id: str
    phase: str | None = None
    container_statuses: List[Dict[str, Any]] | None = None
    node_name: str | None = None
    pod_ip: str | None = None
    reason: str | None = None
    message: str | None = None


class EventInDB(EventBase):
    """Event as stored in database."""

    stored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30))


class EventQuery(BaseModel):
    """Query parameters for event search."""

    event_types: List[EventType] | None = None
    aggregate_id: str | None = None
    correlation_id: str | None = None
    user_id: str | None = None
    service_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    search_text: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    skip: int = Field(default=0, ge=0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_types": [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED],
                "user_id": "user-123",
                "start_time": "2024-01-20T00:00:00Z",
                "end_time": "2024-01-20T23:59:59Z",
                "limit": 100,
                "skip": 0,
            }
        }
    )


class EventStatistics(BaseModel):
    """Event statistics response."""

    total_events: int
    events_by_type: Dict[str, int]
    events_by_service: Dict[str, int]
    events_by_hour: List[HourlyEventCountSchema]
    start_time: datetime | None = None
    end_time: datetime | None = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "total_events": 1543,
                "events_by_type": {
                    EventType.EXECUTION_REQUESTED: 523,
                    EventType.EXECUTION_COMPLETED: 498,
                    EventType.POD_CREATED: 522,
                },
                "events_by_service": {"api-gateway": 523, "execution-service": 1020},
                "events_by_hour": [
                    {"hour": "2024-01-20 10:00", "count": 85},
                    {"hour": "2024-01-20 11:00", "count": 92},
                ],
            }
        },
    )


class EventProjection(BaseModel):
    """Configuration for event projections."""

    name: str
    description: str | None = None
    source_events: List[EventType]  # Event types to include
    aggregation_pipeline: List[Dict[str, Any]]
    output_collection: str
    refresh_interval_seconds: int = 300  # 5 minutes default
    last_updated: datetime | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "execution_summary",
                "description": "Summary of executions by user and status",
                "source_events": [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED],
                "aggregation_pipeline": [
                    {"$match": {"event_type": {"$in": [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED]}}},
                    {
                        "$group": {
                            "_id": {"user_id": "$metadata.user_id", "status": "$payload.status"},
                            "count": {"$sum": 1},
                        }
                    },
                ],
                "output_collection": "execution_summary",
                "refresh_interval_seconds": 300,
            }
        }
    )


class ResourceUsage(BaseModel):
    """Resource usage statistics."""

    cpu_seconds: float
    memory_mb_seconds: float
    disk_io_mb: float
    network_io_mb: float


class PublishEventResponse(BaseModel):
    """Response model for publishing events"""

    event_id: str
    status: str
    timestamp: datetime


class DeleteEventResponse(BaseModel):
    """Response model for deleting events"""

    message: str
    event_id: str
    deleted_at: datetime


class ReplayAggregateResponse(BaseModel):
    """Response model for replaying aggregate events"""

    dry_run: bool
    aggregate_id: str
    event_count: int | None = None
    event_types: List[EventType] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    replayed_count: int | None = None
    replay_correlation_id: str | None = None
