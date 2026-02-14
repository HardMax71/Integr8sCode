from __future__ import annotations

from dataclasses import field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.dataclasses import dataclass

from app.domain.enums import (
    EventType,
    ExecutionStatus,
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
    SSEControlEvent,
)
from app.domain.events.typed import ResourceUsageDomain
from app.domain.execution.models import ExecutionResultDomain


class SSEExecutionStatusDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    status: ExecutionStatus
    timestamp: datetime


class SSEEventDomain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aggregate_id: str
    timestamp: datetime


@dataclass(config=ConfigDict(from_attributes=True))
class RedisSSEMessage:
    """Message structure published to Redis for execution SSE delivery."""

    event_type: EventType
    data: dict[str, Any]
    execution_id: str | None = None


@dataclass(config=ConfigDict(from_attributes=True))
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


@dataclass(config=ConfigDict(from_attributes=True))
class SSEExecutionEventData:
    """Typed model for SSE execution stream event payload.

    This represents the JSON data sent inside each SSE message for execution streams.
    All fields except event_type and execution_id are optional since different
    event types carry different data.
    """

    event_type: EventType | SSEControlEvent
    execution_id: str
    timestamp: datetime | None = None
    event_id: str | None = None
    connection_id: str | None = None
    message: str | None = None
    status: ExecutionStatus | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    timeout_seconds: int | None = None
    resource_usage: ResourceUsageDomain | None = None
    result: ExecutionResultDomain | None = None


@dataclass(config=ConfigDict(from_attributes=True))
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
