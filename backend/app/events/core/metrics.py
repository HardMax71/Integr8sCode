from app.core.metrics import Counter, Histogram

EVENTS_CONSUMED = Counter(
    "events_consumed_total",
    "Total number of events consumed from Kafka",
    ["topic", "event_type", "consumer_group"]
)

EVENTS_PROCESSING_FAILED = Counter(
    "events_processing_failed_total",
    "Total number of events that failed processing",
    ["topic", "event_type", "consumer_group", "error_type"]
)

PROCESSING_DURATION = Histogram(
    "event_consumer_processing_duration_seconds",
    "Time taken to process events",
    ["topic", "event_type", "consumer_group"],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]
)

BATCH_SIZE_PROCESSED = Histogram(
    "event_consumer_batch_size",
    "Size of batches processed",
    ["topic", "consumer_group"],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000]
)

# Producer-specific metrics (different from general Kafka metrics)
EVENTS_SENT = Counter(
    "events_sent_total",
    "Total number of events sent",
    ["topic", "event_type"]
)

EVENTS_FAILED = Counter(
    "events_failed_total",
    "Total number of events failed to send",
    ["topic", "event_type", "error_type"]
)

SEND_DURATION = Histogram(
    "event_send_duration_seconds",
    "Time taken to send events",
    ["topic"],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)

BATCH_SIZE = Histogram(
    "event_batch_size",
    "Size of event batches sent",
    ["topic"],
    buckets=[1, 5, 10, 25, 50, 100, 250, 500]
)

RETRY_COUNT = Counter(
    "event_producer_retry_total",
    "Total number of retry attempts",
    ["topic", "retry_number"]
)

EVENTS_STORED = Counter(
    "event_store_events_stored_total",
    "Total number of events stored",
    ["event_type", "collection"]
)

EVENTS_STORE_FAILED = Counter(
    "event_store_events_failed_total",
    "Total number of events that failed to store",
    ["event_type", "error_type"]
)

STORE_DURATION = Histogram(
    "event_store_duration_seconds",
    "Time taken to store events",
    ["operation", "collection"],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0]
)

QUERY_DURATION = Histogram(
    "event_store_query_duration_seconds",
    "Time taken to query events",
    ["operation", "collection"],
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
)
