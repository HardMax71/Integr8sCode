from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from pydantic.dataclasses import dataclass

from app.core.utils import StringEnum


class IdempotencyStatus(StringEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class IdempotencyRecord:
    key: str
    status: IdempotencyStatus
    event_type: str
    event_id: str
    created_at: datetime
    ttl_seconds: int
    completed_at: Optional[datetime] = None
    processing_duration_ms: Optional[int] = None
    error: Optional[str] = None
    result_json: Optional[str] = None


@dataclass
class IdempotencyStats:
    total_keys: int
    status_counts: Dict[IdempotencyStatus, int]
    prefix: str
