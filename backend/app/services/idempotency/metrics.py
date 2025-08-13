from app.core.metrics import Counter, Gauge, Histogram

# Metrics
IDEMPOTENCY_CACHE_HITS = Counter(
    "idempotency_cache_hits_total",
    "Total number of idempotency cache hits",
    ["event_type", "operation"]
)

IDEMPOTENCY_CACHE_MISSES = Counter(
    "idempotency_cache_misses_total",
    "Total number of idempotency cache misses",
    ["event_type", "operation"]
)

IDEMPOTENCY_DUPLICATES_BLOCKED = Counter(
    "idempotency_duplicates_blocked_total",
    "Total number of duplicate events blocked",
    ["event_type"]
)

IDEMPOTENCY_PROCESSING_DURATION = Histogram(
    "idempotency_processing_duration_seconds",
    "Time taken for idempotency operations",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]
)

IDEMPOTENCY_KEYS_ACTIVE = Gauge(
    "idempotency_keys_active",
    "Number of active idempotency keys in cache",
    ["prefix"]
)
