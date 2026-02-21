from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import (
    EventType,
    ExecutionStatus,
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
    SSEControlEvent,
)
from app.domain.execution.models import ExecutionResultDomain


@dataclass
class SSEExecutionStatusDomain:
    execution_id: str
    status: ExecutionStatus
    timestamp: datetime


@dataclass
class SSEEventDomain:
    aggregate_id: str
    timestamp: datetime


@dataclass
class RedisNotificationMessage:
    """Message structure published to Redis for notification SSE delivery."""

    notification_id: str
    severity: NotificationSeverity
    status: NotificationStatus
    subject: str
    body: str
    created_at: datetime
    tags: list[str] = field(default_factory=list)
    action_url: str = ""


@dataclass
class SSEExecutionEventData:
    """Typed model for SSE execution stream event payload.

    All 7 fields are always present in the wire JSON. Nullable fields carry null
    when not applicable: event_id is null for control events; status only for the
    status control event; message only for failure/cancellation events; result only
    for result_stored.
    """

    event_type: EventType | SSEControlEvent
    execution_id: str
    timestamp: datetime | None = None
    event_id: str | None = None
    status: ExecutionStatus | None = None
    message: str | None = None
    result: ExecutionResultDomain | None = None


@dataclass
class DomainNotificationSSEPayload:
    """Domain model for notification SSE payload."""

    notification_id: str
    channel: NotificationChannel
    status: NotificationStatus
    subject: str
    body: str
    action_url: str
    created_at: datetime
    severity: NotificationSeverity
    tags: list[str]
    read_at: datetime | None = None
