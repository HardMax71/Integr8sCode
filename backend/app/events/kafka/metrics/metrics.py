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


# Kafka consumer metrics
KAFKA_MESSAGES_RECEIVED = Counter(
    "kafka_messages_received_total",
    "Total number of Kafka messages received",
    ["consumer_group", "topic"],
)

KAFKA_CONSUMER_LAG = Gauge(
    "kafka_consumer_lag",
    "Current Kafka consumer lag",
    ["consumer_group", "topic", "partition"],
)

KAFKA_PROCESSING_DURATION = Histogram(
    "kafka_processing_duration_seconds",
    "Time spent processing Kafka messages",
    ["consumer_group", "topic"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

KAFKA_CONSUMER_ERRORS = Counter(
    "kafka_consumer_errors_total",
    "Total number of Kafka consumer errors",
    ["consumer_group", "error_type"],
)

KAFKA_CONSUMER_MESSAGES_CONSUMED = Counter(
    "kafka_consumer_messages_consumed_total",
    "Total number of messages consumed from Kafka",
    ["consumer_group", "topic"],
)

# Additional Kafka consumer metrics (moved from metrics_collector.py)
KAFKA_CONSUMER_BYTES_CONSUMED = Counter(
    "kafka_consumer_bytes_consumed_total",
    "Total number of bytes consumed from Kafka",
    ["consumer_group", "topic"]
)

KAFKA_CONSUMER_REBALANCES = Counter(
    "kafka_consumer_rebalances_total",
    "Total number of consumer group rebalances",
    ["consumer_group"]
)

KAFKA_CONSUMER_OFFSET = Gauge(
    "kafka_consumer_current_offset",
    "Current offset of a consumer group",
    ["consumer_group", "topic", "partition"]
)

KAFKA_CONSUMER_COMMITTED_OFFSET = Gauge(
    "kafka_consumer_committed_offset",
    "Last committed offset of a consumer group",
    ["consumer_group", "topic", "partition"]
)

# Kafka producer metrics
KAFKA_MESSAGES_SENT = Counter(
    "kafka_messages_sent_total",
    "Total number of Kafka messages sent",
    ["topic"],
)

KAFKA_MESSAGES_FAILED = Counter(
    "kafka_messages_failed_total",
    "Total number of failed Kafka message sends",
    ["topic", "error_type"],
)

KAFKA_SEND_DURATION = Histogram(
    "kafka_send_duration_seconds",
    "Time taken to send Kafka messages",
    ["topic"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

# Additional Kafka producer metrics (moved from metrics_collector.py)
KAFKA_PRODUCER_BYTES_SENT = Counter(
    "kafka_producer_bytes_sent_total",
    "Total number of bytes sent to Kafka",
    ["topic"]
)

KAFKA_PRODUCER_RETRIES = Counter(
    "kafka_producer_retries_total",
    "Total number of message send retries",
    ["topic"]
)

KAFKA_PRODUCER_BATCH_SIZE = Histogram(
    "kafka_producer_batch_size",
    "Size of producer batches",
    ["topic"],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000]
)

KAFKA_PRODUCER_QUEUE_SIZE = Gauge(
    "kafka_producer_queue_size",
    "Current size of producer queue",
    ["topic"]
)

# Kafka circuit breaker metrics (from events/cb_healthcheck.py)
CIRCUIT_STATE = Gauge(
    "kafka_circuit_breaker_state",
    "Current state of circuit breaker (0=closed, 1=open, 2=half_open)",
    ["service"]
)

CIRCUIT_TRIPS = Counter(
    "kafka_circuit_breaker_trips_total",
    "Total number of circuit breaker trips",
    ["service"]
)

CIRCUIT_RECOVERIES = Counter(
    "kafka_circuit_breaker_recoveries_total",
    "Total number of circuit breaker recoveries",
    ["service"]
)

# Circuit breaker metrics
# Circuit breaker state metric
# 0 = closed (normal operation)
# 1 = open (rejecting calls)
# 2 = half-open (testing recovery)
CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Current state of circuit breaker (0=closed, 1=open, 2=half-open)",
    ["service", "resource"]
)

# Total circuit breaker calls
CIRCUIT_BREAKER_CALLS = Counter(
    "circuit_breaker_calls_total",
    "Total circuit breaker calls",
    ["service", "resource", "result"]
)

# Circuit breaker state transitions
CIRCUIT_BREAKER_STATE_CHANGES = Counter(
    "circuit_breaker_state_changes_total",
    "Circuit breaker state transitions",
    ["service", "resource", "from_state", "to_state"]
)

# Consecutive failures before circuit opens
CIRCUIT_BREAKER_FAILURES = Histogram(
    "circuit_breaker_consecutive_failures",
    "Number of consecutive failures before opening",
    ["service", "resource"],
    buckets=[1, 3, 5, 10, 20, 50]
)

