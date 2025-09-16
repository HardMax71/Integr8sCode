from app.core.utils import StringEnum


class NotificationChannel(StringEnum):
    """Notification delivery channels."""
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    SLACK = "slack"


class NotificationSeverity(StringEnum):
    """Notification severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(StringEnum):
    """Notification delivery status."""
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"
    READ = "read"
    CLICKED = "clicked"


# SystemNotificationLevel removed in unified model (use NotificationSeverity + tags)
