from datetime import datetime
from typing import TypedDict

from app.domain.enums import NotificationSeverity, NotificationStatus


class NotificationChanges(TypedDict, total=False):
    """Fields a delivery step sets on a notification."""

    status: NotificationStatus
    sent_at: datetime
    delivered_at: datetime
    read_at: datetime
    clicked_at: datetime
    failed_at: datetime
    retry_count: int
    error_message: str | None


class SubscriptionChanges(TypedDict, total=False):
    """Fields an update sets; a missing key keeps the stored value and None clears a nullable one."""

    enabled: bool
    severities: list[NotificationSeverity]
    include_tags: list[str]
    exclude_tags: list[str]
    webhook_url: str | None
    slack_webhook: str | None
    quiet_hours_enabled: bool
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    timezone: str
    batch_interval_minutes: int
