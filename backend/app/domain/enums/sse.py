from app.core.utils import StringEnum


class SSEControlEvent(StringEnum):
    """Control events for execution SSE streams (not from Kafka)."""

    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    HEARTBEAT = "heartbeat"
    SHUTDOWN = "shutdown"
    STATUS = "status"
    ERROR = "error"


class SSENotificationEvent(StringEnum):
    """Event types for notification SSE streams."""

    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    HEARTBEAT = "heartbeat"
    NOTIFICATION = "notification"
