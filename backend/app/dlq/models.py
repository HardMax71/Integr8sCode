import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from confluent_kafka import Message

from app.core.utils import StringEnum
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events import BaseEvent


class DLQMessageStatus(StringEnum):
    """Status of a message in the Dead Letter Queue."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RETRIED = "retried"
    DISCARDED = "discarded"


class RetryStrategy(StringEnum):
    """Retry strategies for DLQ messages."""
    IMMEDIATE = "immediate"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_INTERVAL = "fixed_interval"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class DLQFields(StringEnum):
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


@dataclass
class DLQMessage:
    """Unified DLQ message model for the entire system."""

    # Core fields - always required
    event: BaseEvent  # The original event that failed
    original_topic: str  # Topic where the event originally failed
    error: str  # Error message from the failure
    retry_count: int  # Number of retry attempts
    failed_at: datetime  # When the failure occurred (UTC)
    status: DLQMessageStatus  # Current status
    producer_id: str  # ID of the producer that sent to DLQ

    # Optional fields
    event_id: str | None = None
    created_at: datetime | None = None  # When added to DLQ (UTC)
    last_updated: datetime | None = None  # Last status change (UTC)
    next_retry_at: datetime | None = None  # Next scheduled retry (UTC)
    retried_at: datetime | None = None  # When last retried (UTC)
    discarded_at: datetime | None = None  # When discarded (UTC)
    discard_reason: str | None = None  # Why it was discarded
    dlq_offset: int | None = None  # Kafka offset in DLQ topic
    dlq_partition: int | None = None  # Kafka partition in DLQ topic
    last_error: str | None = None  # Most recent error message

    # Kafka message headers (optional)
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize computed fields."""
        if not self.event_id:
            self.event_id = self.event.event_id
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)

    @property
    def age_seconds(self) -> float:
        """Get message age in seconds since failure."""
        return (datetime.now(timezone.utc) - self.failed_at).total_seconds()

    @property
    def age(self) -> timedelta:
        """Get message age as timedelta."""
        return datetime.now(timezone.utc) - self.failed_at

    @property
    def event_type(self) -> str:
        """Get event type from the event."""
        return str(self.event.event_type)

    def to_dict(self) -> dict[str, object]:
        """Convert to MongoDB document."""
        doc: dict[str, object] = {
            DLQFields.EVENT: self.event.to_dict(),
            DLQFields.ORIGINAL_TOPIC: self.original_topic,
            DLQFields.ERROR: self.error,
            DLQFields.RETRY_COUNT: self.retry_count,
            DLQFields.FAILED_AT: self.failed_at,
            DLQFields.STATUS: self.status,
            DLQFields.PRODUCER_ID: self.producer_id,
        }

        # Add optional fields only if present
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
    def from_dict(cls, data: Mapping[str, object]) -> "DLQMessage":
        """Create from MongoDB document."""

        # Get schema registry for deserialization
        schema_registry = SchemaRegistryManager()

        # Helper for datetime conversion
        def parse_datetime(value: object) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            if isinstance(value, str):
                return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            raise ValueError(f"Cannot parse datetime from {type(value).__name__}")

        # Parse required failed_at field
        failed_at_raw = data.get(DLQFields.FAILED_AT)
        if failed_at_raw is None:
            raise ValueError("Missing required field: failed_at")
        failed_at = parse_datetime(failed_at_raw)
        if failed_at is None:
            raise ValueError("Invalid failed_at value")

        # Parse event data
        event_data = data.get(DLQFields.EVENT)
        if not isinstance(event_data, dict):
            raise ValueError("Missing or invalid event data")

        # Deserialize event
        event = schema_registry.deserialize_json(event_data)

        # Parse status
        status_raw = data.get(DLQFields.STATUS, DLQMessageStatus.PENDING)
        status = DLQMessageStatus(str(status_raw))

        # Extract values with proper types
        retry_count_value: int = data.get(DLQFields.RETRY_COUNT, 0)  # type: ignore[assignment]
        dlq_offset_value: int | None = data.get(DLQFields.DLQ_OFFSET)  # type: ignore[assignment]
        dlq_partition_value: int | None = data.get(DLQFields.DLQ_PARTITION)  # type: ignore[assignment]

        # Create DLQMessage
        return cls(
            event=event,
            original_topic=str(data.get(DLQFields.ORIGINAL_TOPIC, "")),
            error=str(data.get(DLQFields.ERROR, "")),
            retry_count=retry_count_value,
            failed_at=failed_at,
            status=status,
            producer_id=str(data.get(DLQFields.PRODUCER_ID, "unknown")),
            event_id=str(data.get(DLQFields.EVENT_ID, "")) or None,
            created_at=parse_datetime(data.get(DLQFields.CREATED_AT)),
            last_updated=parse_datetime(data.get(DLQFields.LAST_UPDATED)),
            next_retry_at=parse_datetime(data.get(DLQFields.NEXT_RETRY_AT)),
            retried_at=parse_datetime(data.get(DLQFields.RETRIED_AT)),
            discarded_at=parse_datetime(data.get(DLQFields.DISCARDED_AT)),
            discard_reason=str(data.get(DLQFields.DISCARD_REASON, "")) or None,
            dlq_offset=dlq_offset_value,
            dlq_partition=dlq_partition_value,
            last_error=str(data.get(DLQFields.LAST_ERROR, "")) or None,
        )

    @classmethod
    def from_kafka_message(cls, message: Message, schema_registry: SchemaRegistryManager) -> "DLQMessage":
        # Parse message value
        record_value = message.value()
        if record_value is None:
            raise ValueError("Message has no value")

        data = json.loads(record_value.decode('utf-8'))

        # Parse event from the data
        event_data = data.get("event", {})
        event = schema_registry.deserialize_json(event_data)

        # Parse headers
        headers = {}
        msg_headers = message.headers()
        if msg_headers:
            for key, value in msg_headers:
                headers[key] = value.decode('utf-8') if value else ""

        # Parse failed_at
        failed_at_str = data.get("failed_at")
        if failed_at_str:
            failed_at = datetime.fromisoformat(failed_at_str).replace(tzinfo=timezone.utc)
        else:
            failed_at = datetime.now(timezone.utc)

        # Get offset and partition with type assertions
        offset: int = message.offset()  # type: ignore[assignment]
        partition: int = message.partition()  # type: ignore[assignment]

        return cls(
            event=event,
            original_topic=data.get("original_topic", "unknown"),
            error=data.get("error", "Unknown error"),
            retry_count=data.get("retry_count", 0),
            failed_at=failed_at,
            status=DLQMessageStatus.PENDING,
            producer_id=data.get("producer_id", "unknown"),
            headers=headers,
            dlq_offset=offset if offset >= 0 else None,
            dlq_partition=partition if partition >= 0 else None,
        )

    @classmethod
    def from_failed_event(
            cls,
            event: BaseEvent,
            original_topic: str,
            error: str,
            producer_id: str,
            retry_count: int = 0
    ) -> "DLQMessage":
        """Create from a failed event."""
        return cls(
            event=event,
            original_topic=original_topic,
            error=error,
            retry_count=retry_count,
            failed_at=datetime.now(timezone.utc),
            status=DLQMessageStatus.PENDING,
            producer_id=producer_id,
        )

    def to_response_dict(self) -> dict[str, object]:
        """Convert to API response format."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event": self.event.to_dict(),
            "original_topic": self.original_topic,
            "error": self.error,
            "retry_count": self.retry_count,
            "failed_at": self.failed_at,
            "status": self.status,
            "age_seconds": self.age_seconds,
            "producer_id": self.producer_id,
            "dlq_offset": self.dlq_offset,
            "dlq_partition": self.dlq_partition,
            "last_error": self.last_error,
            "next_retry_at": self.next_retry_at,
            "retried_at": self.retried_at,
            "discarded_at": self.discarded_at,
            "discard_reason": self.discard_reason,
        }


@dataclass
class DLQMessageFilter:
    """Filter criteria for querying DLQ messages."""
    status: DLQMessageStatus | None = None
    topic: str | None = None
    event_type: str | None = None

    def to_query(self) -> dict[str, object]:
        """Convert to MongoDB query."""
        query: dict[str, object] = {}

        if self.status:
            query[DLQFields.STATUS] = self.status
        if self.topic:
            query[DLQFields.ORIGINAL_TOPIC] = self.topic
        if self.event_type:
            query[DLQFields.EVENT_TYPE] = self.event_type

        return query


@dataclass
class RetryPolicy:
    """Retry policy configuration for DLQ messages."""
    topic: str
    strategy: RetryStrategy
    max_retries: int = 5
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    retry_multiplier: float = 2.0
    jitter_factor: float = 0.1

    def should_retry(self, message: DLQMessage) -> bool:
        """Check if message should be retried."""
        if self.strategy == RetryStrategy.MANUAL:
            return False
        return message.retry_count < self.max_retries

    def get_next_retry_time(self, message: DLQMessage) -> datetime:
        """Calculate next retry time based on strategy."""
        import random

        if self.strategy == RetryStrategy.IMMEDIATE:
            return datetime.now(timezone.utc)

        if self.strategy == RetryStrategy.FIXED_INTERVAL:
            delay = self.base_delay_seconds

        elif self.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = min(
                self.base_delay_seconds * (self.retry_multiplier ** message.retry_count),
                self.max_delay_seconds
            )
            # Add jitter to avoid thundering herd
            jitter = delay * self.jitter_factor * (2 * random.random() - 1)
            delay = max(0, delay + jitter)

        else:  # SCHEDULED or custom
            delay = self.base_delay_seconds

        return datetime.now(timezone.utc) + timedelta(seconds=delay)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "topic": self.topic,
            "strategy": self.strategy,
            "max_retries": self.max_retries,
            "base_delay_seconds": self.base_delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
            "retry_multiplier": self.retry_multiplier,
            "jitter_factor": self.jitter_factor,
        }


# Statistics models
@dataclass
class TopicStatistic:
    """Statistics for a single topic."""
    topic: str
    count: int
    avg_retry_count: float

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "topic": self.topic,
            "count": self.count,
            "avg_retry_count": self.avg_retry_count,
        }


@dataclass
class EventTypeStatistic:
    """Statistics for a single event type."""
    event_type: str
    count: int

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "event_type": self.event_type,
            "count": self.count,
        }


@dataclass
class AgeStatistics:
    """Age statistics for DLQ messages."""
    min_age_seconds: float
    max_age_seconds: float
    avg_age_seconds: float

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "min_age": self.min_age_seconds,
            "max_age": self.max_age_seconds,
            "avg_age": self.avg_age_seconds,
        }


@dataclass
class DLQStatistics:
    """Comprehensive DLQ statistics."""
    by_status: dict[str, int]
    by_topic: list[TopicStatistic]
    by_event_type: list[EventTypeStatistic]
    age_stats: AgeStatistics
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "by_status": self.by_status,
            "by_topic": self.by_topic,
            "by_event_type": self.by_event_type,
            "age_stats": self.age_stats,
            "timestamp": self.timestamp,
        }


@dataclass
class DLQRetryResult:
    """Result of a single retry operation."""
    event_id: str
    status: str  # "success" or "failed"
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        result: dict[str, object] = {
            "event_id": self.event_id,
            "status": self.status,
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
    details: list[DLQRetryResult]

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "details": [d.to_dict() for d in self.details],
        }


@dataclass
class DLQMessageListResult:
    """Result of listing DLQ messages."""
    messages: list[DLQMessage]
    total: int
    offset: int
    limit: int

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "messages": [msg.to_response_dict() for msg in self.messages],
            "total": self.total,
            "offset": self.offset,
            "limit": self.limit,
        }


@dataclass
class DLQTopicSummary:
    """Summary of a topic in DLQ."""
    topic: str
    total_messages: int
    status_breakdown: dict[str, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary."""
        return {
            "topic": self.topic,
            "total_messages": self.total_messages,
            "status_breakdown": self.status_breakdown,
            "oldest_message": self.oldest_message,
            "newest_message": self.newest_message,
            "avg_retry_count": self.avg_retry_count,
            "max_retry_count": self.max_retry_count,
        }
