from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import NotificationChannel, NotificationSeverity, NotificationStatus

# Templates are removed in the unified model


class Notification(BaseModel):
    """Individual notification instance"""

    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    channel: NotificationChannel
    severity: NotificationSeverity = NotificationSeverity.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING

    # Content
    subject: str
    body: str
    action_url: str = ""
    tags: list[str] = Field(default_factory=list)

    # Tracking
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    clicked_at: datetime | None = None
    failed_at: datetime | None = None

    # Error handling
    retry_count: int = 0
    max_retries: int = Field(3, ge=1)
    error_message: str | None = None

    # Context
    # Removed correlation_id and related_entity_*; use tags/metadata for correlation
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Webhook specific
    webhook_url: str | None = None
    webhook_headers: dict[str, str] | None = None

    @field_validator("scheduled_for")
    @classmethod
    def validate_scheduled_for(cls, v: datetime | None) -> datetime | None:
        if v and v < datetime.now(UTC):
            raise ValueError("scheduled_for must be in the future")
        return v

    model_config = ConfigDict(from_attributes=True)


# Rules removed in unified model


class NotificationSubscription(BaseModel):
    """User subscription preferences for notifications"""

    user_id: str
    channel: NotificationChannel
    severities: list[NotificationSeverity] = Field(default_factory=list)
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    # Channel-specific settings
    webhook_url: str | None = None
    slack_webhook: str | None = None

    # Delivery preferences
    quiet_hours_enabled: bool = False
    quiet_hours_start: str | None = None  # "22:00"
    quiet_hours_end: str | None = None  # "08:00"
    timezone: str = "UTC"

    # Batching preferences
    batch_interval_minutes: int = 60

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(BaseModel):
    """Response schema for notification endpoints"""

    notification_id: str
    channel: NotificationChannel
    status: NotificationStatus
    subject: str
    body: str
    action_url: str
    created_at: datetime
    read_at: datetime | None = None
    severity: NotificationSeverity
    tags: list[str]

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """Response schema for notification list endpoints"""

    notifications: list[NotificationResponse]
    total: int
    unread_count: int

    model_config = ConfigDict(from_attributes=True)


class SubscriptionUpdate(BaseModel):
    """Request schema for updating notification subscriptions"""

    enabled: bool
    severities: list[NotificationSeverity] = Field(default_factory=list)
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    webhook_url: str | None = Field(default=None, pattern=r"^https://")
    slack_webhook: str | None = Field(default=None, pattern=r"^https://hooks\.slack\.com/")
    quiet_hours_enabled: bool = False
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str = "UTC"
    batch_interval_minutes: int = 60

    model_config = ConfigDict(from_attributes=True)


# TestNotificationRequest removed in unified model; use Notification schema directly for test endpoints


class SubscriptionsResponse(BaseModel):
    """Response schema for user subscriptions"""

    subscriptions: list[NotificationSubscription]

    model_config = ConfigDict(from_attributes=True)


class UnreadCountResponse(BaseModel):
    """Response schema for unread notification count"""

    unread_count: int

    model_config = ConfigDict(from_attributes=True)


class DeleteNotificationResponse(BaseModel):
    """Response schema for notification deletion"""

    message: str

    model_config = ConfigDict(from_attributes=True)
