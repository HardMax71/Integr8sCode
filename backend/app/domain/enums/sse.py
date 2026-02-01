from app.core.utils import StringEnum


class SSEControlEvent(StringEnum):
    """Control events for execution SSE streams (not from Kafka)."""

    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    STATUS = "status"
