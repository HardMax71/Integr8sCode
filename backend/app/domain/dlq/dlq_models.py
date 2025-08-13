"""Domain models for Dead Letter Queue (DLQ).

This module provides strongly-typed domain models for DLQ operations
to replace Dict[str, Any] usage throughout the DLQ repository.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, List, Optional

from app.domain.events.event_models import Event


class DLQFields(StrEnum):
    """Database field names for DLQ messages collection."""
    EVENT_ID = "event_id"
    EVENT = "event"
    EVENT_TYPE = "event.event_type"
    ORIGINAL_TOPIC = "original_topic"
    ERROR = "error"
    RETRY_COUNT = "retry_count"
    FAILED_AT = "failed_at"
    STATUS = "status"
    CREATED_AT = "created_at"
    LAST_UPDATED = "last_updated"
    NEXT_RETRY_AT = "next_retry_at"
    RETRIED_AT = "retried_at"
    DISCARDED_AT = "discarded_at"
    DISCARD_REASON = "discard_reason"
    PRODUCER_ID = "producer_id"
    DLQ_OFFSET = "dlq_offset"
    DLQ_PARTITION = "dlq_partition"
    LAST_ERROR = "last_error"


class DLQMessageStatus(StrEnum):
    """Status of a message in the Dead Letter Queue."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RETRIED = "retried"
    DISCARDED = "discarded"


class RetryStrategy(StrEnum):
    """Retry strategies for DLQ messages."""
    IMMEDIATE = "immediate"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_INTERVAL = "fixed_interval"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass
class DLQMessage:
    """DLQ message domain model."""
    event: Event
    original_topic: str
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    producer_id: str
    event_id: Optional[str] = None
    created_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    retried_at: Optional[datetime] = None
    discarded_at: Optional[datetime] = None
    discard_reason: Optional[str] = None
    dlq_offset: Optional[int] = None
    dlq_partition: Optional[int] = None
    last_error: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Post initialization processing."""
        if not self.event_id:
            self.event_id = self.event.event_id
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)
    
    @property
    def age_seconds(self) -> float:
        """Get message age in seconds."""
        return (datetime.now(timezone.utc) - self.failed_at).total_seconds()
    
    @property
    def event_type(self) -> str:
        """Get event type from event data."""
        return self.event.event_type
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        doc: Dict[str, Any] = {
            DLQFields.EVENT: self.event.to_dict(),
            DLQFields.ORIGINAL_TOPIC: self.original_topic,
            DLQFields.ERROR: self.error,
            DLQFields.RETRY_COUNT: self.retry_count,
            DLQFields.FAILED_AT: self.failed_at,
            DLQFields.STATUS: self.status.value,
            DLQFields.PRODUCER_ID: self.producer_id,
        }
        
        # Add optional fields
        if self.event_id:
            doc[DLQFields.EVENT_ID] = self.event_id
        if self.created_at:
            doc[DLQFields.CREATED_AT] = self.created_at
        if self.last_updated:
            doc[DLQFields.LAST_UPDATED] = self.last_updated
        if self.next_retry_at:
            doc[DLQFields.NEXT_RETRY_AT] = self.next_retry_at
        if self.retried_at:
            doc[DLQFields.RETRIED_AT] = self.retried_at
        if self.discarded_at:
            doc[DLQFields.DISCARDED_AT] = self.discarded_at
        if self.discard_reason:
            doc[DLQFields.DISCARD_REASON] = self.discard_reason
        if self.dlq_offset is not None:
            doc[DLQFields.DLQ_OFFSET] = self.dlq_offset
        if self.dlq_partition is not None:
            doc[DLQFields.DLQ_PARTITION] = self.dlq_partition
        if self.last_error:
            doc[DLQFields.LAST_ERROR] = self.last_error
            
        return doc
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DLQMessage":
        """Create from MongoDB document."""
        return cls(
            event=Event.from_dict(data.get(DLQFields.EVENT, {})),
            original_topic=data.get(DLQFields.ORIGINAL_TOPIC, ""),
            error=data.get(DLQFields.ERROR, ""),
            retry_count=data.get(DLQFields.RETRY_COUNT, 0),
            failed_at=data.get(DLQFields.FAILED_AT, datetime.now(timezone.utc)),
            status=DLQMessageStatus(data.get(DLQFields.STATUS, DLQMessageStatus.PENDING)),
            producer_id=data.get(DLQFields.PRODUCER_ID, ""),
            event_id=data.get(DLQFields.EVENT_ID),
            created_at=data.get(DLQFields.CREATED_AT),
            last_updated=data.get(DLQFields.LAST_UPDATED),
            next_retry_at=data.get(DLQFields.NEXT_RETRY_AT),
            retried_at=data.get(DLQFields.RETRIED_AT),
            discarded_at=data.get(DLQFields.DISCARDED_AT),
            discard_reason=data.get(DLQFields.DISCARD_REASON),
            dlq_offset=data.get(DLQFields.DLQ_OFFSET),
            dlq_partition=data.get(DLQFields.DLQ_PARTITION),
            last_error=data.get(DLQFields.LAST_ERROR)
        )
    
    def to_response_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event": self.event.to_dict(),
            "original_topic": self.original_topic,
            "error": self.error,
            "retry_count": self.retry_count,
            "failed_at": self.failed_at,
            "status": self.status.value,
            "age_seconds": self.age_seconds,
            "producer_id": self.producer_id,
            "dlq_offset": self.dlq_offset,
            "dlq_partition": self.dlq_partition,
            "last_error": self.last_error,
            "next_retry_at": self.next_retry_at,
            "retried_at": self.retried_at,
            "discarded_at": self.discarded_at,
            "discard_reason": self.discard_reason
        }


@dataclass
class DLQMessageFilter:
    """DLQ message filter criteria."""
    status: Optional[DLQMessageStatus] = None
    topic: Optional[str] = None
    event_type: Optional[str] = None
    
    def to_query(self) -> Dict[str, Any]:
        """Convert to MongoDB query."""
        query: Dict[str, Any] = {}
        
        if self.status:
            query[DLQFields.STATUS] = self.status.value
        if self.topic:
            query[DLQFields.ORIGINAL_TOPIC] = self.topic
        if self.event_type:
            query[DLQFields.EVENT_TYPE] = self.event_type
            
        return query


@dataclass
class DLQMessageListResult:
    """Result of listing DLQ messages."""
    messages: List[DLQMessage]
    total: int
    offset: int
    limit: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "messages": [msg.to_response_dict() for msg in self.messages],
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit
        }


@dataclass
class DLQTopicSummary:
    """Summary of a topic in DLQ."""
    topic: str
    total_messages: int
    status_breakdown: Dict[str, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "topic": self.topic,
            "total_messages": self.total_messages,
            "status_breakdown": self.status_breakdown,
            "oldest_message": self.oldest_message,
            "newest_message": self.newest_message,
            "avg_retry_count": self.avg_retry_count,
            "max_retry_count": self.max_retry_count
        }


@dataclass
class DLQStatsByStatus:
    """DLQ statistics grouped by status."""
    pending: int = 0
    scheduled: int = 0
    retried: int = 0
    discarded: int = 0
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary."""
        return {
            DLQMessageStatus.PENDING.value: self.pending,
            DLQMessageStatus.SCHEDULED.value: self.scheduled,
            DLQMessageStatus.RETRIED.value: self.retried,
            DLQMessageStatus.DISCARDED.value: self.discarded
        }
    
    @classmethod
    def from_aggregation(cls, data: List[Dict[str, Any]]) -> "DLQStatsByStatus":
        """Create from MongoDB aggregation result."""
        stats = cls()
        for item in data:
            status = item.get("_id")
            count = item.get("count", 0)
            if status == DLQMessageStatus.PENDING:
                stats.pending = count
            elif status == DLQMessageStatus.SCHEDULED:
                stats.scheduled = count
            elif status == DLQMessageStatus.RETRIED:
                stats.retried = count
            elif status == DLQMessageStatus.DISCARDED:
                stats.discarded = count
        return stats


@dataclass
class DLQTopicStats:
    """Statistics for a topic in DLQ."""
    topic: str
    count: int
    avg_retry_count: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "topic": self.topic,
            "count": self.count,
            "avg_retry_count": self.avg_retry_count
        }


@dataclass
class DLQEventTypeStats:
    """Statistics for an event type in DLQ."""
    event_type: str
    count: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_type": self.event_type,
            "count": self.count
        }


@dataclass
class DLQAgeStats:
    """Age statistics for DLQ messages."""
    min_age: float = 0.0
    max_age: float = 0.0
    avg_age: float = 0.0
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "min_age": self.min_age,
            "max_age": self.max_age,
            "avg_age": self.avg_age
        }
    
    @classmethod
    def from_aggregation(cls, data: Optional[Dict[str, Any]]) -> "DLQAgeStats":
        """Create from MongoDB aggregation result."""
        if not data:
            return cls()
        return cls(
            min_age=data.get("min_age", 0.0),
            max_age=data.get("max_age", 0.0),
            avg_age=data.get("avg_age", 0.0)
        )


@dataclass
class DLQStatistics:
    """Complete DLQ statistics."""
    by_status: DLQStatsByStatus
    by_topic: List[DLQTopicStats]
    by_event_type: List[DLQEventTypeStats]
    age_stats: DLQAgeStats
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "by_status": self.by_status.to_dict(),
            "by_topic": [t.to_dict() for t in self.by_topic],
            "by_event_type": [e.to_dict() for e in self.by_event_type],
            "age_stats": self.age_stats.to_dict(),
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class DLQRetryResult:
    """Result of a retry operation."""
    event_id: str
    status: str  # "success" or "failed"
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "event_id": self.event_id,
            "status": self.status
        }
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class DLQBatchRetryResult:
    """Result of batch retry operation."""
    total: int
    successful: int
    failed: int
    details: List[DLQRetryResult]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "details": [d.to_dict() for d in self.details]
        }


@dataclass
class RetryPolicy:
    """Retry policy configuration."""
    topic: str
    strategy: RetryStrategy
    max_retries: int = 5
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    retry_multiplier: float = 2.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "topic": self.topic,
            "strategy": self.strategy.value,
            "max_retries": self.max_retries,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "retry_multiplier": self.retry_multiplier
        }
