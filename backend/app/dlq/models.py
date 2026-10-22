import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NotRequired, TypedDict

from app.core.utils import StringEnum
from app.domain.enums import EventType

# A retried event carries these, so only the consumer group that failed handles it again
DLQ_GROUP_HEADER = "x-dlq-consumer-group"
DLQ_RETRY_HEADER = "x-dlq-retry-count"


class DLQMessageStatus(StringEnum):
    """Status of a message in the Dead Letter Queue."""

    _terminal: bool

    PENDING = "pending"
    SCHEDULED = "scheduled"
    RETRIED = ("retried", True)
    DISCARDED = ("discarded", True)

    def __new__(cls, value: str, terminal: bool = False) -> "DLQMessageStatus":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj._terminal = terminal
        return obj

    @property
    def is_terminal(self) -> bool:
        return self._terminal


DLQ_TERMINAL = frozenset(s for s in DLQMessageStatus if s.is_terminal)


class DLQMessageChanges(TypedDict):
    """Fields a status change sets on a DLQ row; a missing key keeps the stored value."""

    status: DLQMessageStatus
    next_retry_at: NotRequired[datetime]
    retried_at: NotRequired[datetime]
    discarded_at: NotRequired[datetime]
    retry_count: NotRequired[int]
    discard_reason: NotRequired[str]


@dataclass
class DLQMessageFilter:
    """Filter criteria for querying DLQ messages."""

    status: DLQMessageStatus | None = None
    topic: str | None = None
    event_type: EventType | None = None


@dataclass(frozen=True)
class RetryPolicy:
    """When a failed event is retried: exponential backoff with jitter, up to max_retries attempts."""

    max_retries: int = 5
    base_delay_seconds: float = 30.0
    max_delay_seconds: float = 300.0
    retry_multiplier: float = 2.0
    jitter_factor: float = 0.1

    def get_next_retry_time(self, retry_count: int) -> datetime:
        """The time of the next attempt after retry_count failed ones."""
        delay = min(self.base_delay_seconds * (self.retry_multiplier**retry_count), self.max_delay_seconds)
        # Jitter spreads out events that failed together, so their retries don't all land at once
        jitter = delay * self.jitter_factor * (2 * random.random() - 1)
        return datetime.now(timezone.utc) + timedelta(seconds=max(0, delay + jitter))


# Only consumers of execution events save to the DLQ, so one policy covers every row
RETRY_POLICY = RetryPolicy()


@dataclass
class DLQTopicSummary:
    topic: str
    total_messages: int
    status_breakdown: dict[DLQMessageStatus, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int
