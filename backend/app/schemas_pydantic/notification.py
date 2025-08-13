"""Notification models for event-driven notifications"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationChannel(StrEnum):
    """Notification delivery channels"""
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    SLACK = "slack"


class NotificationPriority(StrEnum):
    """Notification priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(StrEnum):
    """Notification delivery status"""
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"
    CLICKED = "clicked"


class NotificationType(StrEnum):
    """Types of notifications"""
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_TIMEOUT = "execution_timeout"
    SYSTEM_UPDATE = "system_update"
    SECURITY_ALERT = "security_alert"
    RESOURCE_LIMIT = "resource_limit"
    ACCOUNT_UPDATE = "account_update"
    SETTINGS_CHANGED = "settings_changed"
    CUSTOM = "custom"


class NotificationTemplate(BaseModel):
    """Notification template for different types"""
    notification_type: NotificationType
    channels: list[NotificationChannel]
    priority: NotificationPriority = NotificationPriority.MEDIUM
    subject_template: str
    body_template: str
    action_url_template: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(
        from_attributes=True
    )


class Notification(BaseModel):
    """Individual notification instance"""
    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    notification_type: NotificationType
    channel: NotificationChannel
    priority: NotificationPriority = NotificationPriority.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING

    # Content
    subject: str
    body: str
    action_url: str | None = None

    # Tracking
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    clicked_at: datetime | None = None
    failed_at: datetime | None = None

    # Error handling
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None

    # Context
    correlation_id: str | None = None
    related_entity_id: str | None = None
    related_entity_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Webhook specific
    webhook_url: str | None = None
    webhook_headers: dict[str, str] | None = None

    @field_validator("scheduled_for")
    @classmethod
    def validate_scheduled_for(cls, v: datetime | None) -> datetime | None:
        if v and v < datetime.now(timezone.utc):
            raise ValueError("scheduled_for must be in the future")
        return v

    model_config = ConfigDict(
        from_attributes=True
    )


class NotificationBatch(BaseModel):
    """Batch of notifications for bulk processing"""
    batch_id: str = Field(default_factory=lambda: str(uuid4()))
    notifications: list[Notification]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_count: int = 0
    failed_count: int = 0

    @field_validator("notifications")
    @classmethod
    def validate_notifications(cls, v: list[Notification]) -> list[Notification]:
        if not v:
            raise ValueError("Batch must contain at least one notification")
        if len(v) > 1000:
            raise ValueError("Batch cannot exceed 1000 notifications")
        return v

    model_config = ConfigDict(
        from_attributes=True
    )


class NotificationRule(BaseModel):
    """Rule for automatic notification generation"""
    rule_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str | None = None
    enabled: bool = True

    # Trigger conditions
    event_types: list[str]
    conditions: dict[str, Any] = Field(default_factory=dict)

    # Actions
    notification_type: NotificationType
    channels: list[NotificationChannel]
    priority: NotificationPriority = NotificationPriority.MEDIUM
    template_id: str | None = None

    # Throttling
    throttle_minutes: int | None = None
    max_per_hour: int | None = None
    max_per_day: int | None = None

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = None

    model_config = ConfigDict(
        from_attributes=True
    )

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one event type must be specified")
        return v


class NotificationSubscription(BaseModel):
    """User subscription preferences for notifications"""
    user_id: str
    channel: NotificationChannel
    notification_types: list[NotificationType]
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

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(
        from_attributes=True
    )


class NotificationStats(BaseModel):
    """Statistics for notification delivery"""
    user_id: str | None = None
    channel: NotificationChannel | None = None
    notification_type: NotificationType | None = None

    # Time range
    start_date: datetime
    end_date: datetime

    # Counts
    total_sent: int = 0
    total_delivered: int = 0
    total_failed: int = 0
    total_read: int = 0
    total_clicked: int = 0

    # Rates
    delivery_rate: float = 0.0
    read_rate: float = 0.0
    click_rate: float = 0.0

    # Performance
    avg_delivery_time_seconds: float = 0.0
    avg_read_time_seconds: float = 0.0

    model_config = ConfigDict(
        from_attributes=True
    )


class NotificationResponse(BaseModel):
    """Response schema for notification endpoints"""
    notification_id: str
    notification_type: NotificationType
    channel: NotificationChannel
    status: NotificationStatus
    subject: str
    body: str
    action_url: str | None
    created_at: datetime
    read_at: datetime | None
    priority: str

    model_config = ConfigDict(
        from_attributes=True
    )


class NotificationListResponse(BaseModel):
    """Response schema for notification list endpoints"""
    notifications: list[NotificationResponse]
    total: int
    unread_count: int

    model_config = ConfigDict(
        from_attributes=True
    )


class SubscriptionUpdate(BaseModel):
    """Request schema for updating notification subscriptions"""
    enabled: bool
    notification_types: list[NotificationType]
    webhook_url: str | None = None
    slack_webhook: str | None = None
    quiet_hours_enabled: bool = False
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str = "UTC"
    batch_interval_minutes: int = 60

    model_config = ConfigDict(
        from_attributes=True
    )


class TestNotificationRequest(BaseModel):
    """Request schema for sending test notifications"""
    notification_type: NotificationType
    channel: NotificationChannel

    model_config = ConfigDict(
        from_attributes=True
    )
