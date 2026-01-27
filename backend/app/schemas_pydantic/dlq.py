from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.dlq import (
    AgeStatistics,
    DLQMessageStatus,
    DLQRetryResult,
    EventTypeStatistic,
    RetryStrategy,
    TopicStatistic,
)
from app.domain.enums.kafka import KafkaTopic
from app.domain.events.typed import DomainEvent


class DLQStats(BaseModel):
    """Statistics for the Dead Letter Queue."""

    model_config = ConfigDict(from_attributes=True)

    by_status: dict[DLQMessageStatus, int]
    by_topic: list[TopicStatistic]
    by_event_type: list[EventTypeStatistic]
    age_stats: AgeStatistics
    timestamp: datetime


class DLQMessageResponse(BaseModel):
    """Response model for a DLQ message. Mirrors DLQMessage for direct model_validate."""

    model_config = ConfigDict(from_attributes=True)

    event: DomainEvent
    original_topic: KafkaTopic
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    producer_id: str
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None
    next_retry_at: datetime | None = None


class RetryPolicyRequest(BaseModel):
    """Request model for setting a retry policy."""

    topic: KafkaTopic
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

    model_config = ConfigDict(from_attributes=True)

    messages: list[DLQMessageResponse]
    total: int
    offset: int
    limit: int


class DLQBatchRetryResponse(BaseModel):
    """Response model for batch retry operation."""

    model_config = ConfigDict(from_attributes=True)

    total: int
    successful: int
    failed: int
    details: list[DLQRetryResult]


class DLQTopicSummaryResponse(BaseModel):
    """Response model for topic summary."""

    model_config = ConfigDict(from_attributes=True)

    topic: KafkaTopic
    total_messages: int
    status_breakdown: dict[str, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int


class DLQMessageDetail(BaseModel):
    """Detailed DLQ message response. Mirrors DLQMessage for direct model_validate."""

    model_config = ConfigDict(from_attributes=True)

    event: DomainEvent
    original_topic: KafkaTopic
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    producer_id: str
    created_at: datetime | None = None
    last_updated: datetime | None = None
    next_retry_at: datetime | None = None
    retried_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    dlq_offset: int | None = None
    dlq_partition: int | None = None
    last_error: str | None = None
