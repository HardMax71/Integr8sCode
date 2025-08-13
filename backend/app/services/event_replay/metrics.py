from app.core.metrics import Counter, Gauge, Histogram

# Metrics
EVENTS_REPLAYED = Counter(
    "event_replay_events_replayed_total",
    "Total number of events replayed",
    ["replay_type", "event_type", "status"]
)

REPLAY_DURATION = Histogram(
    "event_replay_duration_seconds",
    "Time taken to complete replay session",
    ["replay_type"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0]
)

ACTIVE_REPLAYS = Gauge(
    "event_replay_active_sessions",
    "Number of active replay sessions"
)

REPLAY_ERRORS = Counter(
    "event_replay_errors_total",
    "Total number of replay errors",
    ["error_type"]
)
