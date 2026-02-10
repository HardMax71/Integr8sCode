from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.domain.enums import NotificationChannel, NotificationSeverity, NotificationStatus


class NotificationDocument(Document):
    """Individual notification instance.

    Copied from Notification schema.
    """

    notification_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    user_id: Indexed(str)  # type: ignore[valid-type]
    channel: NotificationChannel
    severity: NotificationSeverity = NotificationSeverity.MEDIUM
    status: NotificationStatus = NotificationStatus.PENDING  # Indexed via Settings.indexes

    # Content
    subject: str
    body: str
    action_url: str = ""
    tags: list[str] = Field(default_factory=list)

    # Tracking
    created_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(UTC))  # type: ignore[valid-type]
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
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Webhook specific
    webhook_url: str | None = None
    webhook_headers: dict[str, str] | None = None

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "notifications"
        use_state_management = True
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="idx_notif_user_created_desc"),
            IndexModel([("status", ASCENDING), ("scheduled_for", ASCENDING)], name="idx_notif_status_sched"),
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=30 * 86400, name="idx_notif_ttl"),
        ]


class NotificationSubscriptionDocument(Document):
    """User subscription preferences for notifications.

    Copied from NotificationSubscription schema.
    """

    user_id: Indexed(str)  # type: ignore[valid-type]
    channel: NotificationChannel
    severities: list[NotificationSeverity] = Field(default_factory=list)
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    enabled: bool = True  # Indexed via Settings.indexes

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

    class Settings:
        name = "notification_subscriptions"
        use_state_management = True
        indexes = [
            IndexModel(
                [("user_id", ASCENDING), ("channel", ASCENDING)], name="idx_sub_user_channel_unique", unique=True
            ),
            IndexModel([("enabled", ASCENDING)], name="idx_sub_enabled"),
        ]
