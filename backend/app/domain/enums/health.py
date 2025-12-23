from app.core.utils import StringEnum


class AlertSeverity(StringEnum):
    """Alert severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(StringEnum):
    """Alert status."""

    FIRING = "firing"
    RESOLVED = "resolved"


class ComponentStatus(StringEnum):
    """Health check component status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
