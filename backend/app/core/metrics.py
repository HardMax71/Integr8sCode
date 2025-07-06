from typing import Any, TypeVar

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
    "script_memory_usage_mib", "Memory usage (MiB) per script execution", ["lang_and_version"]
)

ERROR_COUNTER = Counter(
    "script_errors_total",
    "Total number of script errors by type",
    ["error_type"],  # Limited to predefined error types
)

# Pod creation failure metrics
POD_CREATION_FAILURES = Counter(
    "pod_creation_failures_total",
    "Total number of pod creation failures by reason",
    ["failure_reason"],
)

# Queue depth and wait time metrics
QUEUE_DEPTH = Gauge(
    "execution_queue_depth",
    "Current number of executions waiting in queue"
)

QUEUE_WAIT_TIME = Histogram(
    "execution_queue_wait_time_seconds",
    "Time spent waiting in queue before execution starts",
    ["lang_and_version"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# Resource utilization trend metrics
CPU_UTILIZATION = Gauge(
    "script_cpu_utilization_millicores",
    "CPU utilization in millicores per script execution",
    ["lang_and_version"]
)

MEMORY_UTILIZATION_PERCENT = Gauge(
    "script_memory_utilization_percent",
    "Memory utilization as percentage of available memory",
    ["lang_and_version"]
)

# Security event tracking metrics
SECURITY_EVENTS = Counter(
    "security_events_total",
    "Total number of security events by type",
    ["event_type"],
)

NETWORK_POLICY_VIOLATIONS = Counter(
    "network_policy_violations_total",
    "Total number of network policy violations",
    ["policy_name"],
)

PRIVILEGE_ESCALATION_ATTEMPTS = Counter(
    "privilege_escalation_attempts_total",
    "Total number of privilege escalation attempts",
    ["execution_id"],
)
