from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class DLQMessage(BaseModel):
    """Unified DLQ message model. Access event_id/event_type via event.event_id, event.event_type."""

    model_config = ConfigDict(from_attributes=True)

    event: DomainEvent  # Discriminated union - auto-validates from dict
    original_topic: str = ""
    error: str = "Unknown error"
    retry_count: int = 0
    failed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: DLQMessageStatus = DLQMessageStatus.PENDING
    producer_id: str = "unknown"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime | None = None
    next_retry_at: datetime | None = None
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


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
            delay = min(self.base_delay_seconds * (self.retry_multiplier**message.retry_count), self.max_delay_seconds)
            # Add jitter to avoid thundering herd
            jitter = delay * self.jitter_factor * (2 * random.random() - 1)
            delay = max(0, delay + jitter)

        else:  # SCHEDULED or custom
            delay = self.base_delay_seconds

        return datetime.now(timezone.utc) + timedelta(seconds=delay)


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


class DLQTopicSummary(BaseModel):
    """Summary of a topic in DLQ."""

    model_config = ConfigDict(from_attributes=True)

    topic: str
    total_messages: int
    status_breakdown: dict[str, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int
