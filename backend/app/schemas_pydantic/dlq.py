from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.domain.dlq.dlq_models import RetryStrategy
from app.domain.events.event_models import Event


class DLQMessageStatus(StrEnum):
    """Status of a message in the Dead Letter Queue"""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RETRIED = "retried"
    DISCARDED = "discarded"


class DLQStats(BaseModel):
    """Statistics for the Dead Letter Queue"""
    by_status: Dict[str, int]
    by_topic: List[Dict[str, Any]]
    by_event_type: List[Dict[str, Any]]
    age_stats: Dict[str, Any]
    timestamp: str


class DLQMessageResponse(BaseModel):
    """Response model for a DLQ message"""
    event_id: str
    event_type: str
    original_topic: str
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    age_seconds: float
    details: Dict[str, Any]


class RetryPolicyRequest(BaseModel):
    """Request model for setting a retry policy"""
    topic: str
    strategy: RetryStrategy
    max_retries: int = 5
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    retry_multiplier: float = 2.0


class ManualRetryRequest(BaseModel):
    """Request model for manual retry of messages"""
    event_ids: List[str]


class DLQMessagesResponse(BaseModel):
    """Response model for listing DLQ messages"""
    messages: List[DLQMessageResponse]
    total: int
    offset: int
    limit: int


class DLQBatchRetryResponse(BaseModel):
    """Response model for batch retry operation"""
    total: int
    successful: int
    failed: int
    details: List[Dict[str, Any]]


class DLQTopicSummaryResponse(BaseModel):
    """Response model for topic summary"""
    topic: str
    total_messages: int
    status_breakdown: Dict[str, int]
    oldest_message: datetime
    newest_message: datetime
    avg_retry_count: float
    max_retry_count: int


class DLQMessageDetail(BaseModel):
    """Detailed DLQ message response"""
    event_id: str
    event: Event
    event_type: str
    original_topic: str
    error: str
    retry_count: int
    failed_at: datetime
    status: DLQMessageStatus
    created_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    retried_at: Optional[datetime] = None
    discarded_at: Optional[datetime] = None
    discard_reason: Optional[str] = None
    producer_id: str
    dlq_offset: Optional[int] = None
    dlq_partition: Optional[int] = None
    last_error: Optional[str] = None
