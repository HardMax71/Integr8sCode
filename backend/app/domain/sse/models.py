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
    """Notification payload for Redis transport and SSE wire. Defaults cover invariants."""

    notification_id: str
    status: NotificationStatus
    subject: str
    body: str
    action_url: str
    created_at: datetime
    severity: NotificationSeverity
    tags: list[str] = field(default_factory=list)
    channel: NotificationChannel = NotificationChannel.IN_APP
    read_at: datetime | None = None
