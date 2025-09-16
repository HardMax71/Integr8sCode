from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.domain.enums.notification import (
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
)


@dataclass
class DomainNotification:
    notification_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    channel: NotificationChannel = NotificationChannel.IN_APP
    severity: NotificationSeverity = NotificationSeverity.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING

    subject: str = ""
    body: str = ""
    action_url: str | None = None
    tags: list[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    clicked_at: datetime | None = None
    failed_at: datetime | None = None

    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    webhook_url: str | None = None
    webhook_headers: dict[str, str] | None = None


@dataclass
class DomainNotificationSubscription:
    user_id: str
    channel: NotificationChannel
    enabled: bool = True
    severities: list[NotificationSeverity] = field(default_factory=list)
    include_tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    webhook_url: str | None = None
    slack_webhook: str | None = None

    quiet_hours_enabled: bool = False
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str = "UTC"
    batch_interval_minutes: int = 60

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DomainNotificationListResult:
    notifications: list[DomainNotification]
    total: int
    unread_count: int
