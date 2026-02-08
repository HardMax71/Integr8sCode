from app.core.metrics.base import BaseMetrics
from app.domain.enums import ExecutionStatus


class ExecutionMetrics(BaseMetrics):
    """Metrics for script execution tracking."""

    def _create_instruments(self) -> None:
        self.script_executions = self._meter.create_counter(
            name="script.executions.total", description="Total number of script executions", unit="1"
        )

        self.execution_events = self._meter.create_observable_gauge(
            name="script.execution.events",
            description="Instantaneous execution events (1 when execution starts, 0 otherwise)",
            unit="1",
        )

        self.execution_duration = self._meter.create_histogram(
            name="script.execution.duration", description="Time spent executing scripts in seconds", unit="s"
        )

        self.active_executions = self._meter.create_up_down_counter(
            name="script.executions.active", description="Number of currently running script executions", unit="1"
        )

        self.memory_usage = self._meter.create_histogram(
            name="script.memory.usage", description="Memory usage per script execution in MiB", unit="MiB"
        )

        self.cpu_utilization = self._meter.create_histogram(
            name="script.cpu.utilization",
            description="CPU utilization in millicores per script execution",
            unit="millicores",
        )

        self.memory_utilization_percent = self._meter.create_histogram(
            name="script.memory.utilization.percent",
            description="Memory utilization as percentage of available memory",
            unit="%",
        )

        self.error_counter = self._meter.create_counter(
            name="script.errors.total", description="Total number of script errors by type", unit="1"
        )

        self.executions_assigned = self._meter.create_counter(
            name="executions.assigned.total", description="Total number of executions assigned to workers", unit="1"
        )

        self.executions_queued = self._meter.create_counter(
            name="executions.queued.total", description="Total number of executions queued", unit="1"
        )

        self.queue_depth = self._meter.create_up_down_counter(
            name="execution.queue.depth", description="Current number of executions waiting in queue", unit="1"
        )

        self.queue_wait_time = self._meter.create_histogram(
            name="execution.queue.wait_time",
            description="Time spent waiting in queue before execution starts in seconds",
            unit="s",
        )

    def record_script_execution(self, status: ExecutionStatus, lang_and_version: str) -> None:
        self.script_executions.add(1, attributes={"status": status, "lang_and_version": lang_and_version})

    def record_execution_duration(self, duration_seconds: float, lang_and_version: str) -> None:
        self.execution_duration.record(duration_seconds, attributes={"lang_and_version": lang_and_version})

    def increment_active_executions(self) -> None:
        self.active_executions.add(1)

    def decrement_active_executions(self) -> None:
        self.active_executions.add(-1)

    def record_memory_usage(self, memory_mib: float, lang_and_version: str) -> None:
        self.memory_usage.record(memory_mib, attributes={"lang_and_version": lang_and_version})

    def record_error(self, error_type: str) -> None:
        self.error_counter.add(1, attributes={"error_type": error_type})

    def update_queue_depth(self, delta: int) -> None:
        self.queue_depth.add(delta)

    def record_queue_wait_time(self, wait_seconds: float, lang_and_version: str) -> None:
        self.queue_wait_time.record(wait_seconds, attributes={"lang_and_version": lang_and_version})

    def record_execution_assigned(self) -> None:
        self.executions_assigned.add(1)

    def record_execution_queued(self) -> None:
        self.executions_queued.add(1)

    def record_execution_scheduled(self, status: str) -> None:
        self.executions_assigned.add(1)

    def update_cpu_available(self, cores: float) -> None:
        self.cpu_utilization.record(cores)

    def update_memory_available(self, memory_mb: float) -> None:
        self.memory_usage.record(memory_mb, attributes={"lang_and_version": "resource_manager"})

    def update_gpu_available(self, count: int) -> None:
        self.cpu_utilization.record(float(count), attributes={"resource": "gpu"})

    def update_allocations_active(self, count: int) -> None:
        self.memory_utilization_percent.record(float(count), attributes={"metric": "allocations"})
