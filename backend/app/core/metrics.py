from app.config import get_settings
from prometheus_client import Counter, Histogram, Gauge

ALLOWED_STATUSES = ["success", "error", "timeout", "invalid_input"]


class BoundedLabelsCounter(Counter):
    def labels(self, *args, **kwargs):
        # Validate labels before creating new time series
        if 'python_version' in kwargs and kwargs['python_version'] not in get_settings().SUPPORTED_PYTHON_VERSIONS:
            kwargs['python_version'] = 'unknown'
        if 'status' in kwargs and kwargs['status'] not in ALLOWED_STATUSES:
            kwargs['status'] = 'unknown'
        return super().labels(*args, **kwargs)


# Metrics with bounded labels
SCRIPT_EXECUTIONS = BoundedLabelsCounter(
    "script_executions_total",
    "Total number of script executions",
    ["status", "python_version"]
)

EXECUTION_DURATION = Histogram(
    "script_execution_duration_seconds",
    "Time spent executing scripts",
    ["python_version"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]  # Define specific buckets
)

ACTIVE_EXECUTIONS = Gauge(
    "active_executions",
    "Number of currently running script executions"
)

# Resource usage metrics
MEMORY_USAGE = Gauge(
    "script_memory_usage_bytes",
    "Memory usage per script execution",
    ["python_version"]
)

ERROR_COUNTER = Counter(
    "script_errors_total",
    "Total number of script errors by type",
    ["error_type"]  # Limited to predefined error types
)
