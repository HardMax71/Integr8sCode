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

# Event-specific metrics
EVENT_PUBLISHED = Counter(
    "events_published_total",
    "Total number of events published",
    ["event_type", "aggregate_type"],
)

EVENT_PROCESSING_DURATION = Histogram(
    "event_processing_duration_seconds",
    "Time spent processing events",
    ["event_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

SSE_ACTIVE_CONNECTIONS = Gauge(
    "sse_active_connections",
    "Number of active Server-Sent Events connections",
    ["endpoint"],
)

SSE_MESSAGES_SENT = Counter(
    "sse_messages_sent_total",
    "Total number of SSE messages sent",
    ["endpoint", "event_type"],
)

SSE_CONNECTION_DURATION = Histogram(
    "sse_connection_duration_seconds",
    "Duration of SSE connections",
    ["endpoint"],
    buckets=[1, 10, 30, 60, 300, 600, 1800, 3600],
)

EVENT_BUS_SUBSCRIBERS = Gauge(
    "event_bus_subscribers",
    "Number of active event bus subscribers",
    ["event_type"],
)

EVENT_BUS_QUEUE_SIZE = Gauge(
    "event_bus_queue_size",
    "Size of event bus message queue",
    ["event_type"],
)

MONGODB_EVENT_OPERATIONS = Counter(
    "mongodb_event_operations_total",
    "Total MongoDB operations for events",
    ["operation", "status"],
)

MONGODB_EVENT_QUERY_DURATION = Histogram(
    "mongodb_event_query_duration_seconds",
    "Duration of MongoDB event queries",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

POD_EVENT_PUBLISHED = Counter(
    "pod_events_published_total",
    "Total number of pod events published",
    ["event_type", "phase"],
)

EVENT_REPLAY_OPERATIONS = Counter(
    "event_replay_operations_total",
    "Total number of event replay operations",
    ["status"],
)

EVENT_PROJECTION_UPDATES = Counter(
    "event_projection_updates_total",
    "Total number of event projection updates",
    ["projection_name", "status"],
)


# Event buffer metrics
EVENT_BUFFER_SIZE = Gauge(
    "event_buffer_size",
    "Current number of events in buffer",
    ["priority"],
)

EVENT_BUFFER_DROPPED = Counter(
    "event_buffer_dropped_total",
    "Total number of events dropped from buffer",
    ["event_type", "reason"],
)

EVENT_BUFFER_PROCESSED = Counter(
    "event_buffer_processed_total",
    "Total number of events processed from buffer",
    ["event_type"],
)

EVENT_BUFFER_LATENCY = Histogram(
    "event_buffer_latency_seconds",
    "Time between event creation and processing",
    ["event_type"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

EVENT_BUFFER_BACKPRESSURE = Gauge(
    "event_buffer_backpressure_active",
    "Whether backpressure is currently active",
    ["buffer_name"],
)

EVENT_BUFFER_MEMORY_USAGE = Gauge(
    "event_buffer_memory_usage_mb",
    "Memory usage of event buffer in MB",
    ["buffer_name"],
)

# SSE shutdown metrics
SSE_DRAINING_CONNECTIONS = Gauge(
    "sse_draining_connections",
    "Number of SSE connections being drained during shutdown",
    ["phase"],
)

SSE_SHUTDOWN_DURATION = Gauge(
    "sse_shutdown_duration_seconds",
    "Time taken for SSE shutdown phases",
    ["phase"],
)

# Notification metrics
NOTIFICATIONS_SENT = Counter(
    "notifications_sent_total",
    "Total number of notifications sent",
    ["channel", "notification_type"],
)

NOTIFICATIONS_FAILED = Counter(
    "notifications_failed_total",
    "Total number of failed notifications",
    ["channel", "notification_type", "error_type"],
)

NOTIFICATION_DELIVERY_TIME = Histogram(
    "notification_delivery_seconds",
    "Time taken to deliver notifications",
    ["channel", "notification_type"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Execution coordinator metrics
COORDINATOR_PROCESSING_TIME = Histogram(
    "coordinator_processing_time_seconds",
    "Time spent processing execution events",
    ["event_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

EXECUTIONS_ASSIGNED = Counter(
    "executions_assigned_total",
    "Total number of executions assigned to workers",
    ["worker_id"],
)

EXECUTIONS_QUEUED = Counter(
    "executions_queued_total",
    "Total number of executions queued"
)

# Health check metrics
# Health check status gauge
# 1 = healthy, 0 = unhealthy
HEALTH_CHECK_STATUS = Gauge(
    "health_check_status",
    "Health check status (1=healthy, 0=unhealthy)",
    ["service", "check_name"]
)

# Health check duration histogram
HEALTH_CHECK_DURATION = Histogram(
    "health_check_duration_seconds",
    "Time taken to perform health check",
    ["service", "check_name"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

# Health check failures counter
HEALTH_CHECK_FAILURES = Counter(
    "health_check_failures_total",
    "Total number of health check failures",
    ["service", "check_name", "failure_type"]
)

