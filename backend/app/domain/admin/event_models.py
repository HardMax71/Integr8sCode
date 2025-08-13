"""Domain models for admin events.

This module provides strongly-typed domain models to replace Dict[str, Any]
usage throughout the admin events repository.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional


class EventFields(StrEnum):
    """Database field names for events collection."""
    EVENT_ID = "event_id"
    EVENT_TYPE = "event_type"
    EVENT_VERSION = "event_version"
    TIMESTAMP = "timestamp"
    AGGREGATE_ID = "aggregate_id"
    CORRELATION_ID = "correlation_id"
    CAUSATION_ID = "causation_id"
    METADATA = "metadata"
    PAYLOAD = "payload"
    STATUS = "status"
    ERROR = "error"
    
    # Nested metadata fields
    METADATA_USER_ID = "metadata.user_id"
    METADATA_SERVICE_NAME = "metadata.service_name"
    METADATA_SERVICE_VERSION = "metadata.service_version"
    METADATA_IP_ADDRESS = "metadata.ip_address"
    METADATA_SESSION_ID = "metadata.session_id"
    
    # Nested payload fields
    PAYLOAD_DURATION_SECONDS = "payload.duration_seconds"


class CollectionNames(StrEnum):
    """MongoDB collection names."""
    EVENTS = "events"
    EVENT_STORE = "event_store"
    REPLAY_SESSIONS = "replay_sessions"
    EVENTS_ARCHIVE = "events_archive"


class ReplaySessionStatus(StrEnum):
    """Replay session status values."""
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SortDirection:
    """MongoDB sort directions."""
    ASCENDING = 1
    DESCENDING = -1


@dataclass
class EventMetadata:
    """Event metadata domain model."""
    user_id: Optional[str] = None
    service_name: Optional[str] = None
    service_version: Optional[str] = None
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        return {
            k: v for k, v in {
                "user_id": self.user_id,
                "service_name": self.service_name,
                "service_version": self.service_version,
                "ip_address": self.ip_address,
                "session_id": self.session_id
            }.items() if v is not None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventMetadata":
        """Create from MongoDB document."""
        return cls(
            user_id=data.get("user_id"),
            service_name=data.get("service_name"),
            service_version=data.get("service_version"),
            ip_address=data.get("ip_address"),
            session_id=data.get("session_id")
        )


@dataclass
class Event:
    """Event domain model."""
    event_id: str
    event_type: str
    timestamp: datetime
    metadata: EventMetadata
    payload: Dict[str, Any]
    event_version: str = "1.0"
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        doc: Dict[str, Any] = {
            EventFields.EVENT_ID.value: self.event_id,
            EventFields.EVENT_TYPE.value: self.event_type,
            EventFields.EVENT_VERSION.value: self.event_version,
            EventFields.TIMESTAMP.value: self.timestamp,
            EventFields.METADATA.value: self.metadata.to_dict(),
            EventFields.PAYLOAD.value: self.payload
        }
        
        # Add optional fields
        if self.aggregate_id:
            doc[EventFields.AGGREGATE_ID.value] = self.aggregate_id
        if self.correlation_id:
            doc[EventFields.CORRELATION_ID.value] = self.correlation_id
        if self.causation_id:
            doc[EventFields.CAUSATION_ID.value] = self.causation_id
        if self.status:
            doc[EventFields.STATUS.value] = self.status
        if self.error:
            doc[EventFields.ERROR.value] = self.error
            
        return doc
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create from MongoDB document."""
        return cls(
            event_id=data.get(EventFields.EVENT_ID.value, ""),
            event_type=data.get(EventFields.EVENT_TYPE.value, ""),
            event_version=data.get(EventFields.EVENT_VERSION.value, "1.0"),
            timestamp=data.get(EventFields.TIMESTAMP.value, datetime.now()),
            aggregate_id=data.get(EventFields.AGGREGATE_ID.value),
            correlation_id=data.get(EventFields.CORRELATION_ID.value),
            causation_id=data.get(EventFields.CAUSATION_ID.value),
            metadata=EventMetadata.from_dict(data.get(EventFields.METADATA.value, {})),
            payload=data.get(EventFields.PAYLOAD.value, {}),
            status=data.get(EventFields.STATUS.value),
            error=data.get(EventFields.ERROR.value)
        )


@dataclass
class EventSummary:
    """Lightweight event summary for lists and previews."""
    event_id: str
    event_type: str
    timestamp: datetime
    aggregate_id: Optional[str] = None
    
    @classmethod
    def from_event(cls, event: Event) -> "EventSummary":
        """Create summary from full event."""
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            aggregate_id=event.aggregate_id
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventSummary":
        """Create from MongoDB document."""
        return cls(
            event_id=data.get(EventFields.EVENT_ID, ""),
            event_type=data.get(EventFields.EVENT_TYPE, ""),
            timestamp=data.get(EventFields.TIMESTAMP, datetime.now()),
            aggregate_id=data.get(EventFields.AGGREGATE_ID)
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp
        }
        if self.aggregate_id:
            result["aggregate_id"] = self.aggregate_id
        return result


@dataclass
class EventFilter:
    """Event filter criteria."""
    event_types: Optional[List[str]] = None
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    service_name: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    search_text: Optional[str] = None
    
    def to_query(self) -> Dict[str, Any]:
        """Convert to MongoDB query."""
        query: Dict[str, Any] = {}
        
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
        
        # Time range
        if self.start_time or self.end_time:
            time_query = {}
            if self.start_time:
                time_query["$gte"] = self.start_time
            if self.end_time:
                time_query["$lte"] = self.end_time
            query[EventFields.TIMESTAMP] = time_query
        
        # Text search
        if self.search_text:
            query["$or"] = [
                {EventFields.EVENT_TYPE: {"$regex": self.search_text, "$options": "i"}},
                {EventFields.AGGREGATE_ID: {"$regex": self.search_text, "$options": "i"}},
                {EventFields.CORRELATION_ID: {"$regex": self.search_text, "$options": "i"}},
                {EventFields.METADATA_USER_ID: {"$regex": self.search_text, "$options": "i"}},
                {EventFields.METADATA_SERVICE_NAME: {"$regex": self.search_text, "$options": "i"}}
            ]
        
        return query


@dataclass
class EventBrowseResult:
    """Result of browsing events."""
    events: List[Event]
    total: int
    skip: int
    limit: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "events": [event.to_dict() for event in self.events],
            "total": self.total,
            "skip": self.skip,
            "limit": self.limit
        }


@dataclass
class EventDetail:
    """Detailed event information including related events."""
    event: Event
    related_events: List[EventSummary] = field(default_factory=list)
    timeline: List[EventSummary] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "event": self.event.to_dict(),
            "related_events": [e.to_dict() for e in self.related_events],
            "timeline": [e.to_dict() for e in self.timeline]
        }


@dataclass
class EventTypeCount:
    """Event type with count."""
    event_type: str
    count: int


@dataclass
class HourlyEventCount:
    """Hourly event count."""
    hour: str
    count: int


@dataclass
class UserEventCount:
    """User event count."""
    user_id: str
    event_count: int


@dataclass
class EventStatistics:
    """Event statistics."""
    total_events: int
    events_by_type: Dict[str, int]
    events_by_hour: List[HourlyEventCount]
    top_users: List[UserEventCount]
    error_rate: float
    avg_processing_time: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "total_events": self.total_events,
            "events_by_type": self.events_by_type,
            "events_by_hour": [{"hour": h.hour, "count": h.count} for h in self.events_by_hour],
            "top_users": [{"user_id": u.user_id, "event_count": u.event_count} for u in self.top_users],
            "error_rate": self.error_rate,
            "avg_processing_time": self.avg_processing_time
        }


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
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for CSV export."""
        return {
            "Event ID": self.event_id,
            "Event Type": self.event_type,
            "Timestamp": self.timestamp,
            "Correlation ID": self.correlation_id,
            "Aggregate ID": self.aggregate_id,
            "User ID": self.user_id,
            "Service": self.service,
            "Status": self.status,
            "Error": self.error
        }
    
    @classmethod
    def from_event(cls, event: Event) -> "EventExportRow":
        """Create from event."""
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp.isoformat() if event.timestamp else "",
            correlation_id=event.correlation_id or "",
            aggregate_id=event.aggregate_id or "",
            user_id=event.metadata.user_id or "",
            service=event.metadata.service_name or "",
            status=event.status or "",
            error=event.error or ""
        )
