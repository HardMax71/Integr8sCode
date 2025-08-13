"""Domain models for event store."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional, Union

# Type for MongoDB query values
MongoQueryValue = Union[
    str,  # Simple string values
    Dict[str, Union[str, List[str], datetime]],  # MongoDB operators like $in, $gte, $lte, $search
]
MongoQuery = Dict[str, MongoQueryValue]


class EventFields(StrEnum):
    """Database field names for events collection."""
    ID = "_id"
    EVENT_ID = "event_id"
    EVENT_TYPE = "event_type"
    EVENT_VERSION = "event_version"
    TIMESTAMP = "timestamp"
    AGGREGATE_ID = "aggregate_id"
    CORRELATION_ID = "correlation_id"
    CAUSATION_ID = "causation_id"
    METADATA = "metadata"
    PAYLOAD = "payload"
    STORED_AT = "stored_at"
    TTL_EXPIRES_AT = "ttl_expires_at"
    STATUS = "status"

    # Metadata sub-fields
    METADATA_USER_ID = "metadata.user_id"
    METADATA_SERVICE_NAME = "metadata.service_name"
    METADATA_SERVICE_VERSION = "metadata.service_version"
    METADATA_IP_ADDRESS = "metadata.ip_address"
    METADATA_USER_AGENT = "metadata.user_agent"
    METADATA_SESSION_ID = "metadata.session_id"
    METADATA_TRACE_ID = "metadata.trace_id"
    METADATA_SPAN_ID = "metadata.span_id"

    # Payload sub-fields for common queries
    PAYLOAD_EXECUTION_ID = "payload.execution_id"
    PAYLOAD_POD_NAME = "payload.pod_name"

    # Archive fields
    DELETED_AT = "_deleted_at"
    DELETED_BY = "_deleted_by"
    DELETION_REASON = "_deletion_reason"


class EventSortOrder(StrEnum):
    """Sort order for event queries."""
    ASC = "asc"
    DESC = "desc"


@dataclass
class EventMetadata:
    """Event metadata for auditing and tracing."""
    service_name: str
    service_version: str
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            EventFields.METADATA_USER_ID.split('.')[-1]: self.user_id,
            EventFields.METADATA_SERVICE_NAME.split('.')[-1]: self.service_name,
            EventFields.METADATA_SERVICE_VERSION.split('.')[-1]: self.service_version,
            EventFields.METADATA_IP_ADDRESS.split('.')[-1]: self.ip_address,
            EventFields.METADATA_USER_AGENT.split('.')[-1]: self.user_agent,
            EventFields.METADATA_SESSION_ID.split('.')[-1]: self.session_id,
            EventFields.METADATA_TRACE_ID.split('.')[-1]: self.trace_id,
            EventFields.METADATA_SPAN_ID.split('.')[-1]: self.span_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventMetadata":
        """Create from dictionary."""
        return cls(
            user_id=data.get("user_id"),
            service_name=data.get("service_name", "unknown"),
            service_version=data.get("service_version", "1.0"),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            session_id=data.get("session_id"),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
        )


@dataclass
class Event:
    """Domain model for an event."""
    event_id: str
    event_type: str
    event_version: str
    timestamp: datetime
    metadata: EventMetadata
    payload: Dict[str, Any]
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    stored_at: Optional[datetime] = None
    ttl_expires_at: Optional[datetime] = None
    status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        doc: Dict[str, Any] = {
            EventFields.EVENT_ID: self.event_id,
            EventFields.EVENT_TYPE: self.event_type,
            EventFields.EVENT_VERSION: self.event_version,
            EventFields.TIMESTAMP: self.timestamp,
            EventFields.AGGREGATE_ID: self.aggregate_id,
            EventFields.CORRELATION_ID: self.correlation_id,
            EventFields.CAUSATION_ID: self.causation_id,
            EventFields.METADATA: self.metadata.to_dict(),
            EventFields.PAYLOAD: self.payload,
        }

        if self.stored_at:
            doc[EventFields.STORED_AT] = self.stored_at
        if self.ttl_expires_at:
            doc[EventFields.TTL_EXPIRES_AT] = self.ttl_expires_at
        if self.status:
            doc[EventFields.STATUS] = self.status

        return doc

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create from dictionary."""
        # Handle timestamp conversion
        timestamp = data.get(EventFields.TIMESTAMP)
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)

        # Handle stored_at conversion
        stored_at = data.get(EventFields.STORED_AT)
        if isinstance(stored_at, str):
            stored_at = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))

        # Handle ttl_expires_at conversion
        ttl_expires_at = data.get(EventFields.TTL_EXPIRES_AT)
        if isinstance(ttl_expires_at, str):
            ttl_expires_at = datetime.fromisoformat(ttl_expires_at.replace("Z", "+00:00"))

        return cls(
            event_id=data.get(EventFields.EVENT_ID, ""),
            event_type=data.get(EventFields.EVENT_TYPE, ""),
            event_version=data.get(EventFields.EVENT_VERSION, "1.0"),
            timestamp=timestamp,
            aggregate_id=data.get(EventFields.AGGREGATE_ID),
            correlation_id=data.get(EventFields.CORRELATION_ID),
            causation_id=data.get(EventFields.CAUSATION_ID),
            metadata=EventMetadata.from_dict(data.get(EventFields.METADATA, {})),
            payload=data.get(EventFields.PAYLOAD, {}),
            stored_at=stored_at,
            ttl_expires_at=ttl_expires_at,
            status=data.get(EventFields.STATUS),
        )


@dataclass
class EventFilter:
    """Filter criteria for querying events."""
    event_types: Optional[List[str]] = None
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    service_name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    text_search: Optional[str] = None
    status: Optional[str] = None

    def to_query(self) -> MongoQuery:
        """Convert to MongoDB query."""
        query: MongoQuery = {}

        if self.event_types:
            query[EventFields.EVENT_TYPE] = {"$in": self.event_types}
        if self.aggregate_id:
            query[EventFields.AGGREGATE_ID] = self.aggregate_id
        if self.correlation_id:
            query[EventFields.CORRELATION_ID] = self.correlation_id
        if self.user_id:
            query[EventFields.METADATA_USER_ID] = self.user_id
        if self.service_name:
            query[EventFields.METADATA_SERVICE_NAME] = self.service_name
        if self.status:
            query[EventFields.STATUS] = self.status

        if self.start_time or self.end_time:
            time_query: Dict[str, Union[str, List[str], datetime]] = {}
            if self.start_time:
                time_query["$gte"] = self.start_time
            if self.end_time:
                time_query["$lte"] = self.end_time
            query[EventFields.TIMESTAMP] = time_query

        if self.text_search:
            query["$text"] = {"$search": self.text_search}

        return query


@dataclass
class EventQuery:
    """Query parameters for event search."""
    filter: EventFilter
    sort_by: str = EventFields.TIMESTAMP
    sort_order: EventSortOrder = EventSortOrder.DESC
    limit: int = 100
    skip: int = 0

    def get_sort_direction(self) -> int:
        """Get MongoDB sort direction."""
        return -1 if self.sort_order == EventSortOrder.DESC else 1


@dataclass
class EventListResult:
    """Result of event list query."""
    events: List[Event]
    total: int
    skip: int
    limit: int
    has_more: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "events": [event.to_dict() for event in self.events],
            "total": self.total,
            "skip": self.skip,
            "limit": self.limit,
            "has_more": self.has_more,
        }


@dataclass
class EventStatistics:
    """Event statistics."""
    total_events: int
    events_by_type: Dict[str, int] = field(default_factory=dict)
    events_by_service: Dict[str, int] = field(default_factory=dict)
    events_by_hour: List[Dict[str, Any]] = field(default_factory=list)
    time_range: Optional[Dict[str, datetime]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "total_events": self.total_events,
            "events_by_type": self.events_by_type,
            "events_by_service": self.events_by_service,
            "events_by_hour": self.events_by_hour,
        }

        if self.time_range:
            result["time_range"] = {
                "start": self.time_range.get("start"),
                "end": self.time_range.get("end"),
            }

        return result


@dataclass
class EventProjection:
    """Configuration for event projections."""
    name: str
    pipeline: List[Dict[str, Any]]
    output_collection: str
    description: Optional[str] = None
    source_events: Optional[List[str]] = None
    refresh_interval_seconds: int = 300
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "source_events": self.source_events,
            "pipeline": self.pipeline,
            "output_collection": self.output_collection,
            "refresh_interval_seconds": self.refresh_interval_seconds,
            "last_updated": self.last_updated,
        }


@dataclass
class ArchivedEvent(Event):
    """Archived event with deletion metadata."""
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = None
    deletion_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        doc = super().to_dict()
        doc.update({
            EventFields.DELETED_AT: self.deleted_at,
            EventFields.DELETED_BY: self.deleted_by,
            EventFields.DELETION_REASON: self.deletion_reason,
        })
        return doc

    @classmethod
    def from_event(
            cls,
            event: Event,
            deleted_by: str,
            deletion_reason: str
    ) -> "ArchivedEvent":
        """Create archived event from regular event."""
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            timestamp=event.timestamp,
            aggregate_id=event.aggregate_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            metadata=event.metadata,
            payload=event.payload,
            stored_at=event.stored_at,
            ttl_expires_at=event.ttl_expires_at,
            status=event.status,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=deleted_by,
            deletion_reason=deletion_reason,
        )


@dataclass
class EventReplayInfo:
    """Information for event replay."""
    events: List[Event]
    event_count: int
    event_types: List[str]
    time_range: Dict[str, datetime]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "events": [event.to_dict() for event in self.events],
            "event_count": self.event_count,
            "event_types": self.event_types,
            "time_range": self.time_range,
        }


@dataclass
class ExecutionEventsResult:
    """Result of execution events query."""
    events: List[Event]
    access_allowed: bool
    include_system_events: bool

    def to_response_list(self) -> List[Dict[str, Any]]:
        """Convert to response list."""
        if not self.access_allowed:
            return []

        events = self.events
        if not self.include_system_events:
            events = [
                e for e in events
                if not e.metadata.service_name.startswith("system-")
            ]

        return [event.to_dict() for event in events]


@dataclass
class EventAggregationResult:
    """Result of event aggregation."""
    results: List[Dict[str, Any]]
    pipeline: List[Dict[str, Any]]
    execution_time_ms: Optional[float] = None

    def to_list(self) -> List[Dict[str, Any]]:
        """Convert to list of results."""
        return self.results
