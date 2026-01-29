from app.core.metrics.base import BaseMetrics


class CoordinatorMetrics(BaseMetrics):
    """Metrics for coordinator and scheduling operations."""

    def _create_instruments(self) -> None:
        self.coordinator_scheduling_duration = self._meter.create_histogram(
            name="coordinator.scheduling.duration",
            description="Time spent scheduling executions in seconds",
            unit="s",
        )

        self.coordinator_active_executions = self._meter.create_up_down_counter(
            name="coordinator.executions.active",
            description="Number of active executions managed by coordinator",
            unit="1",
        )

        self.coordinator_queue_time = self._meter.create_histogram(
            name="coordinator.queue.wait_time",
            description="Time spent waiting in coordinator queue by priority",
            unit="s",
        )

        self.execution_request_queue_depth = self._meter.create_up_down_counter(
            name="execution.queue.depth",
            description="Depth of user execution requests queued",
            unit="1",
        )

        self.coordinator_executions_scheduled = self._meter.create_counter(
            name="coordinator.executions.scheduled.total",
            description="Total number of executions scheduled",
            unit="1",
        )

    def record_coordinator_scheduling_duration(self, duration_seconds: float) -> None:
        self.coordinator_scheduling_duration.record(duration_seconds)

    def update_coordinator_active_executions(self, count: int) -> None:
        current = getattr(self, "_active_current", 0)
        delta = count - current
        if delta != 0:
            self.coordinator_active_executions.add(delta)
        self._active_current = count

    def record_coordinator_queue_time(self, wait_seconds: float, priority: str) -> None:
        self.coordinator_queue_time.record(wait_seconds, attributes={"priority": priority})

    def update_execution_request_queue_size(self, size: int) -> None:
        """Update the execution-only request queue depth (absolute value)."""
        current = getattr(self, "_queue_depth_current", 0)
        delta = size - current
        if delta != 0:
            self.execution_request_queue_depth.add(delta)
        self._queue_depth_current = size

    def record_coordinator_execution_scheduled(self, status: str) -> None:
        self.coordinator_executions_scheduled.add(1, attributes={"status": status})
