from app.core.metrics.base import BaseMetrics


class ConnectionMetrics(BaseMetrics):
    """Metrics for SSE connections."""

    def _create_instruments(self) -> None:
        self.sse_active_connections = self._meter.create_up_down_counter(
            name="sse.connections.active", description="Number of active Server-Sent Events connections", unit="1"
        )

        self.sse_messages_sent = self._meter.create_counter(
            name="sse.messages.sent.total", description="Total number of SSE messages sent", unit="1"
        )

        self.sse_connection_duration = self._meter.create_histogram(
            name="sse.connection.duration", description="Duration of SSE connections in seconds", unit="s"
        )

        self.sse_draining_connections = self._meter.create_up_down_counter(
            name="sse.connections.draining",
            description="Number of SSE connections being drained during shutdown",
            unit="1",
        )

    def increment_sse_connections(self, endpoint: str = "default") -> None:
        self.sse_active_connections.add(1, attributes={"endpoint": endpoint})

    def decrement_sse_connections(self, endpoint: str = "default") -> None:
        self.sse_active_connections.add(-1, attributes={"endpoint": endpoint})

    def record_sse_message_sent(self, endpoint: str, event_type: str) -> None:
        self.sse_messages_sent.add(1, attributes={"endpoint": endpoint, "event_type": event_type})

    def record_sse_connection_duration(self, duration_seconds: float, endpoint: str) -> None:
        self.sse_connection_duration.record(duration_seconds, attributes={"endpoint": endpoint})

    def update_sse_draining_connections(self, delta: int) -> None:
        self.sse_draining_connections.add(delta)
