from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.dlq import DLQMessageStatus, RetryStrategy
from app.domain.enums.events import EventType


class DLQStats(BaseModel):
    """Statistics for the Dead Letter Queue."""

    by_status: dict[str, int]
    by_topic: list[dict[str, Any]]
    by_event_type: list[dict[str, Any]]
    age_stats: dict[str, Any]
    timestamp: datetime


class DLQMessageResponse(BaseModel):
    """Response model for a DLQ message."""

    event_id: str
    event_type: EventType
    original_topic: str
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    age_seconds: float
    details: dict[str, Any]


class RetryPolicyRequest(BaseModel):
    """Request model for setting a retry policy."""

    topic: str
    strategy: RetryStrategy
    max_retries: int = 5
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    retry_multiplier: float = 2.0


class ManualRetryRequest(BaseModel):
    """Request model for manual retry of messages."""

    event_ids: list[str]


class DLQMessagesResponse(BaseModel):
    """Response model for listing DLQ messages."""

    messages: list[DLQMessageResponse]
    total: int
    offset: int
    limit: int


class DLQBatchRetryResponse(BaseModel):
    """Response model for batch retry operation."""

    total: int
    successful: int
    failed: int
    details: list[dict[str, Any]]


class DLQTopicSummaryResponse(BaseModel):
    """Response model for topic summary."""

    topic: str
    total_messages: int
    status_breakdown: dict[str, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int


class DLQMessageDetail(BaseModel):
    """Detailed DLQ message response."""

    event_id: str
    event: dict[str, Any]  # BaseEvent as dict
    event_type: EventType
    original_topic: str
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    created_at: datetime | None = None
    last_updated: datetime | None = None
    next_retry_at: datetime | None = None
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    producer_id: str
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None
