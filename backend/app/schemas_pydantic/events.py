"""Event-related schemas for REST API endpoints.

This module contains Pydantic models for event-related API requests and responses.
For Avro-based event schemas used in Kafka streaming, see app.schemas_avro.event_schemas.
"""
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas_avro.event_schemas import EventType


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class EventResponse(BaseModel):
    event_id: str
    event_type: EventType
    event_version: str
    timestamp: datetime
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    metadata: Dict[str, Any]
    payload: Dict[str, Any]
    stored_at: Optional[datetime] = None


class EventListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    limit: int
    skip: int
    has_more: bool


class EventFilterRequest(BaseModel):
    """Request model for filtering events."""
    event_types: Optional[List[EventType]] = Field(None, description="Filter by event types")
    aggregate_id: Optional[str] = Field(None, description="Filter by aggregate ID")
    correlation_id: Optional[str] = Field(None, description="Filter by correlation ID")
    user_id: Optional[str] = Field(None, description="Filter by user ID (admin only)")
    service_name: Optional[str] = Field(None, description="Filter by service name")
    start_time: Optional[datetime] = Field(None, description="Filter events after this time")
    end_time: Optional[datetime] = Field(None, description="Filter events before this time")
    text_search: Optional[str] = Field(None, description="Full-text search in event data")
    sort_by: str = Field("timestamp", description="Field to sort by")
    sort_order: SortOrder = Field(SortOrder.DESC, description="Sort order")
    limit: int = Field(100, ge=1, le=1000, description="Maximum events to return")
    skip: int = Field(0, ge=0, description="Number of events to skip")

    @field_validator("sort_by")
    @classmethod
    def validate_sort_field(cls, v: str) -> str:
        allowed_fields = {
            "timestamp", "event_type", "aggregate_id",
            "correlation_id", "stored_at"
        }
        if v not in allowed_fields:
            raise ValueError(f"Sort field must be one of {allowed_fields}")
        return v


class EventAggregationRequest(BaseModel):
    """Request model for event aggregation queries."""
    pipeline: List[Dict[str, Any]] = Field(
        ...,
        description="MongoDB aggregation pipeline"
    )
    limit: int = Field(100, ge=1, le=1000)


class PublishEventRequest(BaseModel):
    """Request model for publishing events."""
    event_type: EventType = Field(..., description="Type of event to publish")
    payload: Dict[str, Any] = Field(..., description="Event payload data")
    aggregate_id: Optional[str] = Field(None, description="Aggregate root ID")
    correlation_id: Optional[str] = Field(None, description="Correlation ID")
    causation_id: Optional[str] = Field(None, description="ID of causing event")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class EventMetadata(BaseModel):
    """Metadata for event auditing and tracing in API responses."""
    user_id: Optional[str] = None
    service_name: str
    service_version: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    model_config = ConfigDict(
        extra="allow"  # Allow additional metadata fields
    )


class EventBase(BaseModel):
    """Base event model for API responses."""
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    event_version: str = "1.0"
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())  # Unix timestamp
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None  # ID of the event that caused this event
    metadata: EventMetadata
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
                    "ip_address": "192.168.1.1"
                },
                "payload": {
                    "execution_id": "execution-123",
                    "script": "print('hello')",
                    "language": "python",
                    "version": "3.11"
                }
            }
        }
    )


class ExecutionEventPayload(BaseModel):
    """Common payload for execution-related events in API responses."""
    execution_id: str
    user_id: str
    status: Optional[str] = None
    script: Optional[str] = None
    language: Optional[str] = None
    language_version: Optional[str] = None
    output: Optional[str] = None
    errors: Optional[str] = None
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None


class PodEventPayload(BaseModel):
    """Common payload for pod-related events in API responses."""
    pod_name: str
    namespace: str
    execution_id: str
    phase: Optional[str] = None
    container_statuses: Optional[List[Dict[str, Any]]] = None
    node_name: Optional[str] = None
    pod_ip: Optional[str] = None
    reason: Optional[str] = None
    message: Optional[str] = None


class EventInDB(EventBase):
    """Event as stored in database."""
    stored_at: float = Field(default_factory=lambda: datetime.now().timestamp())  # Unix timestamp
    ttl_expires_at: float = Field(default_factory=lambda: datetime.now().timestamp() + (30 * 24 * 60 * 60))  # 30d TTL


class EventQuery(BaseModel):
    """Query parameters for event search."""
    event_types: Optional[List[EventType]] = None
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    service_name: Optional[str] = None
    start_time: Optional[float] = None  # Unix timestamp
    end_time: Optional[float] = None  # Unix timestamp
    text_search: Optional[str] = None
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
                "skip": 0
            }
        }
    )


class EventStatistics(BaseModel):
    """Event statistics response."""
    total_events: int
    events_by_type: Dict[str, int]
    events_by_service: Dict[str, int]
    events_by_hour: List[Dict[str, Any]]
    time_range: Optional[Dict[str, datetime]] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_events": 1543,
                "events_by_type": {
                    EventType.EXECUTION_REQUESTED: 523,
                    EventType.EXECUTION_COMPLETED: 498,
                    EventType.POD_CREATED: 522
                },
                "events_by_service": {
                    "api-gateway": 523,
                    "execution-service": 1020
                },
                "events_by_hour": [
                    {"hour": "2024-01-20 10:00", "count": 85},
                    {"hour": "2024-01-20 11:00", "count": 92}
                ]
            }
        }
    )


class EventProjection(BaseModel):
    """Configuration for event projections."""
    name: str
    description: Optional[str] = None
    source_events: List[EventType]  # Event types to include
    aggregation_pipeline: List[Dict[str, Any]]
    output_collection: str
    refresh_interval_seconds: int = 300  # 5 minutes default
    last_updated: Optional[datetime] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "execution_summary",
                "description": "Summary of executions by user and status",
                "source_events": [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED],
                "aggregation_pipeline": [
                    {"$match": {"event_type": {"$in": [EventType.EXECUTION_REQUESTED,
                                                       EventType.EXECUTION_COMPLETED]}}},
                    {"$group": {
                        "_id": {
                            "user_id": "$metadata.user_id",
                            "status": "$payload.status"
                        },
                        "count": {"$sum": 1}
                    }}
                ],
                "output_collection": "execution_summary",
                "refresh_interval_seconds": 300
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
    timestamp: str


class DeleteEventResponse(BaseModel):
    """Response model for deleting events"""
    message: str
    event_id: str
    deleted_at: str


class ReplayAggregateResponse(BaseModel):
    """Response model for replaying aggregate events"""
    dry_run: bool
    aggregate_id: str
    event_count: Optional[int] = None
    event_types: Optional[List[str]] = None
    time_range: Optional[Dict[str, Any]] = None
    replayed_count: Optional[int] = None
    replay_correlation_id: Optional[str] = None
