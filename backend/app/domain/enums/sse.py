from app.core.utils import StringEnum


class SSEHealthStatus(StringEnum):
    """Health status for SSE service."""

    HEALTHY = "healthy"
    DRAINING = "draining"


class SSEControlEvent(StringEnum):
    """Control events for execution SSE streams (not from Kafka)."""

    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    HEARTBEAT = "heartbeat"
    SHUTDOWN = "shutdown"
    STATUS = "status"
    ERROR = "error"
