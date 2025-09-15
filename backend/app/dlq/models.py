from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.utils import StringEnum
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
    event_id: str = ""
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
    def event_type(self) -> str:
        """Get event type from the event."""
        return str(self.event.event_type)


@dataclass
class DLQMessageUpdate:
    """Strongly-typed update descriptor for DLQ message status changes."""
    status: DLQMessageStatus
    next_retry_at: datetime | None = None
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    retry_count: int | None = None
    discard_reason: str | None = None
    last_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DLQMessageFilter:
    """Filter criteria for querying DLQ messages."""
    status: DLQMessageStatus | None = None
    topic: str | None = None
    event_type: str | None = None


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


# Statistics models
@dataclass
class TopicStatistic:
    """Statistics for a single topic."""
    topic: str
    count: int
    avg_retry_count: float


@dataclass
class EventTypeStatistic:
    """Statistics for a single event type."""
    event_type: str
    count: int


@dataclass
class AgeStatistics:
    """Age statistics for DLQ messages."""
    min_age_seconds: float
    max_age_seconds: float
    avg_age_seconds: float


@dataclass
class DLQStatistics:
    """Comprehensive DLQ statistics."""
    by_status: dict[str, int]
    by_topic: list[TopicStatistic]
    by_event_type: list[EventTypeStatistic]
    age_stats: AgeStatistics
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DLQRetryResult:
    """Result of a single retry operation."""
    event_id: str
    status: str  # "success" or "failed"
    error: str | None = None


@dataclass
class DLQBatchRetryResult:
    """Result of batch retry operation."""
    total: int
    successful: int
    failed: int
    details: list[DLQRetryResult]


@dataclass
class DLQMessageListResult:
    """Result of listing DLQ messages."""
    messages: list[DLQMessage]
    total: int
    offset: int
    limit: int


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
