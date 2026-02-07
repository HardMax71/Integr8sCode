from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.notification import (
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
)


class DomainNotification(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    channel: NotificationChannel = NotificationChannel.IN_APP
    severity: NotificationSeverity = NotificationSeverity.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING

    subject: str = ""
    body: str = ""
    action_url: str | None = None
    tags: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    clicked_at: datetime | None = None
    failed_at: datetime | None = None

    retry_count: int = 0
    max_retries: int = Field(3, ge=1)
    error_message: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    webhook_url: str | None = None
    webhook_headers: dict[str, str] | None = None


class DomainNotificationSubscription(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    channel: NotificationChannel
    enabled: bool = True
    severities: list[NotificationSeverity] = Field(default_factory=list)
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    webhook_url: str | None = None
    slack_webhook: str | None = None

    quiet_hours_enabled: bool = False
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str = "UTC"
    batch_interval_minutes: int = 60

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DomainNotificationListResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notifications: list[DomainNotification]
    total: int
    unread_count: int


class DomainNotificationCreate(BaseModel):
    """Data for creating a notification."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    channel: NotificationChannel
    subject: str
    body: str
    severity: NotificationSeverity = NotificationSeverity.MEDIUM
    action_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    scheduled_for: datetime | None = None
    webhook_url: str | None = None
    webhook_headers: dict[str, str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DomainNotificationUpdate(BaseModel):
    """Data for updating a notification."""

    model_config = ConfigDict(from_attributes=True)

    status: NotificationStatus | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    clicked_at: datetime | None = None
    failed_at: datetime | None = None
    retry_count: int | None = None
    error_message: str | None = None


class DomainSubscriptionUpdate(BaseModel):
    """Data for updating a subscription."""

    model_config = ConfigDict(from_attributes=True)

    enabled: bool | None = None
    severities: list[NotificationSeverity] | None = None
    include_tags: list[str] | None = None
    exclude_tags: list[str] | None = None
    webhook_url: str | None = None
    slack_webhook: str | None = None
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None
    batch_interval_minutes: int | None = None
