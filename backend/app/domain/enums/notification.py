from app.core.utils import StringEnum


class NotificationChannel(StringEnum):
    """Notification delivery channels."""
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    SLACK = "slack"


class NotificationPriority(StringEnum):
    """Notification priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(StringEnum):
    """Notification delivery status."""
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"
    CLICKED = "clicked"


class NotificationType(StringEnum):
    """Types of notifications."""
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_TIMEOUT = "execution_timeout"
    SYSTEM_UPDATE = "system_update"
    SYSTEM_ALERT = "system_alert"
    SECURITY_ALERT = "security_alert"
    RESOURCE_LIMIT = "resource_limit"
    QUOTA_WARNING = "quota_warning"
    ACCOUNT_UPDATE = "account_update"
    SETTINGS_CHANGED = "settings_changed"
    MAINTENANCE = "maintenance"
    CUSTOM = "custom"
