from app.core.metrics.base import BaseMetrics


class QueueMetrics(BaseMetrics):
    """Metrics for execution queue operations."""

    def _create_instruments(self) -> None:
        self._queue_depth = self._meter.create_up_down_counter(
            name="queue.depth",
            description="Number of pending executions in the queue",
            unit="1",
        )
        self._queue_active = self._meter.create_up_down_counter(
            name="queue.active",
            description="Number of actively running executions",
            unit="1",
        )
        self._enqueue_total = self._meter.create_counter(
            name="queue.enqueue.total",
            description="Total number of executions enqueued",
            unit="1",
        )
        self._schedule_total = self._meter.create_counter(
            name="queue.schedule.total",
            description="Total number of executions scheduled from queue",
            unit="1",
        )
        self._wait_time = self._meter.create_histogram(
            name="queue.wait_time",
            description="Time spent waiting in queue before scheduling",
            unit="s",
        )

    def record_enqueue(self) -> None:
        self._enqueue_total.add(1)
        self._queue_depth.add(1)

    def record_schedule(self) -> None:
        self._schedule_total.add(1)
        self._queue_depth.add(-1)
        self._queue_active.add(1)

    def record_release(self) -> None:
        self._queue_active.add(-1)

    def record_wait_time(self, wait_seconds: float, priority: str) -> None:
        self._wait_time.record(wait_seconds, attributes={"priority": priority})
