from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.utils import StringEnum
from app.domain.enums import EventType
from app.domain.events import DomainEvent


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


@dataclass
class DLQMessage:
    """Unified DLQ message model. Access event_id/event_type via event.event_id, event.event_type."""

    event: DomainEvent
    original_topic: str = ""
    error: str = "Unknown error"
    retry_count: int = 0
    failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: DLQMessageStatus = DLQMessageStatus.PENDING
    producer_id: str = "unknown"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime | None = None
    next_retry_at: datetime | None = None
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None


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
    event_type: EventType | None = None


@dataclass
class RetryPolicy:
    """Retry policy configuration for DLQ messages."""

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
            delay = min(self.base_delay_seconds * (self.retry_multiplier**message.retry_count), self.max_delay_seconds)
            # Add jitter to avoid thundering herd
            jitter = delay * self.jitter_factor * (2 * random.random() - 1)
            delay = max(0, delay + jitter)

        else:  # SCHEDULED or custom
            delay = self.base_delay_seconds

        return datetime.now(timezone.utc) + timedelta(seconds=delay)


AGGRESSIVE_RETRY = RetryPolicy(
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    max_retries=5, base_delay_seconds=30, max_delay_seconds=300, retry_multiplier=2.0,
)
CAUTIOUS_RETRY = RetryPolicy(
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    max_retries=3, base_delay_seconds=60, max_delay_seconds=600, retry_multiplier=3.0,
)
IMMEDIATE_RETRY = RetryPolicy(strategy=RetryStrategy.IMMEDIATE, max_retries=3)
DEFAULT_RETRY = RetryPolicy(
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    max_retries=4, base_delay_seconds=60, max_delay_seconds=1800, retry_multiplier=2.5,
)


def retry_policy_for(event_type: EventType) -> RetryPolicy:
    """Determine retry policy from event type using category sets."""
    from app.infrastructure.kafka.topics import COMMAND_TYPES, EXECUTION_TYPES, POD_TYPES, RESULT_TYPES

    if event_type in EXECUTION_TYPES:
        return AGGRESSIVE_RETRY
    if event_type in POD_TYPES:
        return CAUTIOUS_RETRY
    if event_type in COMMAND_TYPES:
        return AGGRESSIVE_RETRY
    if event_type in RESULT_TYPES:
        return IMMEDIATE_RETRY
    return DEFAULT_RETRY


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
    topic: str
    total_messages: int
    status_breakdown: dict[DLQMessageStatus, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int
