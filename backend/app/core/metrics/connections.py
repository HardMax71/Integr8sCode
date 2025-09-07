from app.core.metrics.base import BaseMetrics


class ConnectionMetrics(BaseMetrics):
    """Metrics for SSE connections and event bus."""
    
    def _create_instruments(self) -> None:
        self.sse_active_connections = self._meter.create_up_down_counter(
            name="sse.connections.active",
            description="Number of active Server-Sent Events connections",
            unit="1"
        )
        
        self.sse_messages_sent = self._meter.create_counter(
            name="sse.messages.sent.total",
            description="Total number of SSE messages sent",
            unit="1"
        )
        
        self.sse_connection_duration = self._meter.create_histogram(
            name="sse.connection.duration",
            description="Duration of SSE connections in seconds",
            unit="s"
        )
        
        self.sse_draining_connections = self._meter.create_up_down_counter(
            name="sse.connections.draining",
            description="Number of SSE connections being drained during shutdown",
            unit="1"
        )
        
        self.sse_shutdown_duration = self._meter.create_histogram(
            name="sse.shutdown.duration",
            description="Time taken for SSE shutdown phases in seconds",
            unit="s"
        )
        
        # Event bus metrics
        self.event_bus_subscribers = self._meter.create_up_down_counter(
            name="event.bus.subscribers",
            description="Number of active event bus subscribers by pattern",
            unit="1"
        )
        
        self.event_bus_subscriptions = self._meter.create_up_down_counter(
            name="event.bus.subscriptions.total",
            description="Total number of event bus subscriptions",
            unit="1"
        )
    
    def increment_sse_connections(self, endpoint: str = "default") -> None:
        self.sse_active_connections.add(1, attributes={"endpoint": endpoint})
    
    def decrement_sse_connections(self, endpoint: str = "default") -> None:
        self.sse_active_connections.add(-1, attributes={"endpoint": endpoint})
    
    def record_sse_message_sent(self, endpoint: str, event_type: str) -> None:
        self.sse_messages_sent.add(
            1,
            attributes={"endpoint": endpoint, "event_type": event_type}
        )
    
    def record_sse_connection_duration(self, duration_seconds: float, endpoint: str) -> None:
        self.sse_connection_duration.record(
            duration_seconds,
            attributes={"endpoint": endpoint}
        )
    
    def update_sse_draining_connections(self, delta: int) -> None:
        self.sse_draining_connections.add(delta)
    
    def record_sse_shutdown_duration(self, duration_seconds: float, phase: str) -> None:
        self.sse_shutdown_duration.record(
            duration_seconds,
            attributes={"phase": phase}
        )
    
    def update_sse_shutdown_duration(self, duration_seconds: float, phase: str) -> None:
        self.sse_shutdown_duration.record(
            duration_seconds,
            attributes={"phase": phase}
        )
    
    def increment_event_bus_subscriptions(self) -> None:
        self.event_bus_subscriptions.add(1)
    
    def decrement_event_bus_subscriptions(self, count: int = 1) -> None:
        self.event_bus_subscriptions.add(-count)
    
    def update_event_bus_subscribers(self, count: int, pattern: str) -> None:
        """Update the count of event bus subscribers for a specific pattern."""
        # This tracks the current number of subscribers for a pattern
        # We need to track the delta from the previous value
        # Since we can't store state in metrics, we record the absolute value
        # The metric system will handle the up/down nature
        self.event_bus_subscribers.add(
            count,
            attributes={"pattern": pattern}
        )
