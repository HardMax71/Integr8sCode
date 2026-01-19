from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from app.core.utils import StringEnum


class ProducerState(StringEnum):
    """Kafka producer state enumeration."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ConsumerState(StringEnum):
    """Kafka consumer state enumeration."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(slots=True)
class ConsumerConfig:
    """Kafka consumer configuration."""

    bootstrap_servers: str
    group_id: str
    client_id: str = "integr8scode-consumer"

    # Offset management
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False

    # Session configuration
    session_timeout_ms: int = 45000
    heartbeat_interval_ms: int = 10000
    max_poll_interval_ms: int = 300000
    request_timeout_ms: int = 40000

    # Fetch configuration
    max_poll_records: int = 500
    fetch_min_bytes: int = 1
    fetch_max_wait_ms: int = 500


@dataclass(slots=True)
class ProducerMetrics:
    """Metrics tracking for Kafka producer."""

    # Message counters
    messages_sent: int = 0
    messages_failed: int = 0
    bytes_sent: int = 0

    # Performance metrics
    queue_size: int = 0
    avg_latency_ms: float = 0.0

    # Error tracking
    last_error: str | None = None
    last_error_time: datetime | None = None


@dataclass(slots=True)
class ConsumerMetrics:
    """Metrics tracking for Kafka consumer."""

    # Message counters
    messages_consumed: int = 0
    bytes_consumed: int = 0

    # Performance metrics
    consumer_lag: int = 0

    # Error tracking
    commit_failures: int = 0
    processing_errors: int = 0

    # Timestamps
    last_message_time: datetime | None = None
    last_updated: datetime | None = None

    def __post_init__(self) -> None:
        """Initialize timestamps if not provided."""
        self.last_updated = self.last_updated or datetime.now(timezone.utc)


class ConsumerMetricsSnapshot(BaseModel):
    """Snapshot of consumer metrics for status reporting."""

    model_config = ConfigDict(from_attributes=True)

    messages_consumed: int
    bytes_consumed: int
    consumer_lag: int
    commit_failures: int
    processing_errors: int
    last_message_time: datetime | None
    last_updated: datetime | None


class ConsumerStatus(BaseModel):
    """Consumer status information."""

    model_config = ConfigDict(from_attributes=True)

    state: str
    group_id: str
    client_id: str
    metrics: ConsumerMetricsSnapshot
