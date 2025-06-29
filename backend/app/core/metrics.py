from typing import Any, TypeVar

from app.config import get_settings
from prometheus_client import Counter, Gauge, Histogram

ALLOWED_STATUSES = ["success", "error", "timeout", "invalid_input"]

T = TypeVar('T', bound='BoundedLabelsCounter')


class BoundedLabelsCounter(Counter):
    def labels(self, *args: Any, **kwargs: Any) -> 'BoundedLabelsCounter':
        # Validate labels before creating new time series
        if "status" in kwargs and kwargs["status"] not in ALLOWED_STATUSES:
            kwargs["status"] = "unknown"
        return super().labels(*args, **kwargs)


# Metrics with bounded labels
SCRIPT_EXECUTIONS = BoundedLabelsCounter(
    "script_executions_total",
    "Total number of script executions",
    ["status", "lang_and_version"],
)

EXECUTION_DURATION = Histogram(
    "script_execution_duration_seconds",
    "Time spent executing scripts",
    ["lang_and_version"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],  # Define specific buckets
)

ACTIVE_EXECUTIONS = Gauge(
    "active_executions", "Number of currently running script executions"
)

# Resource usage metrics
MEMORY_USAGE = Gauge(
    "script_memory_usage_bytes", "Memory usage per script execution", ["lang_and_version"]
)

ERROR_COUNTER = Counter(
    "script_errors_total",
    "Total number of script errors by type",
    ["error_type"],  # Limited to predefined error types
)
