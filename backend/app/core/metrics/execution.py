from app.core.metrics.base import BaseMetrics
from app.domain.enums import ExecutionStatus


class ExecutionMetrics(BaseMetrics):
    """Metrics for script execution tracking."""

    def _create_instruments(self) -> None:
        self.script_executions = self._meter.create_counter(
            name="script.executions.total", description="Total number of script executions", unit="1"
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

        self.memory_utilization_percent = self._meter.create_histogram(
            name="script.memory.utilization.percent",
            description="Memory utilization as percentage of available memory",
            unit="%",
        )

        self.error_counter = self._meter.create_counter(
            name="script.errors.total", description="Total number of script errors by type", unit="1"
        )

        self.submission_duration = self._meter.create_histogram(
            name="script.submission.duration",
            description="Time to persist and publish an execution request in seconds",
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

    def record_submission_duration(self, duration_seconds: float, lang_and_version: str) -> None:
        self.submission_duration.record(duration_seconds, attributes={"lang_and_version": lang_and_version})
