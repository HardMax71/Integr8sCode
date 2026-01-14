from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
class ProducerConfig:
    """Kafka producer configuration."""

    bootstrap_servers: str
    client_id: str = "integr8scode-producer"

    # Batching configuration
    batch_size: int = 16384
    linger_ms: int = 10
    compression_type: str = "gzip"

    # Reliability configuration
    request_timeout_ms: int = 30000
    retries: int = 3
    enable_idempotence: bool = True
    acks: str = "all"
    max_in_flight_requests_per_connection: int = 5

    def to_producer_config(self) -> dict[str, Any]:
        """Convert to Confluent Kafka producer configuration."""
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "client.id": self.client_id,
            "batch.size": self.batch_size,
            "linger.ms": self.linger_ms,
            "compression.type": self.compression_type,
            "request.timeout.ms": self.request_timeout_ms,
            "retries": self.retries,
            "enable.idempotence": self.enable_idempotence,
            "acks": self.acks,
            "max.in.flight.requests.per.connection": self.max_in_flight_requests_per_connection,
        }


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
    session_timeout_ms: int = 30000
    heartbeat_interval_ms: int = 3000
    max_poll_interval_ms: int = 300000
    request_timeout_ms: int = 40000

    # Fetch configuration
    max_poll_records: int = 500
    fetch_min_bytes: int = 1
    fetch_max_wait_ms: int = 500

    # Monitoring
    statistics_interval_ms: int = 30000

    def to_consumer_config(self) -> dict[str, object]:
        """Convert to Confluent Kafka consumer configuration."""
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "client.id": self.client_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
            "session.timeout.ms": self.session_timeout_ms,
            "heartbeat.interval.ms": self.heartbeat_interval_ms,
            "max.poll.interval.ms": self.max_poll_interval_ms,
            "fetch.min.bytes": self.fetch_min_bytes,
            "fetch.wait.max.ms": self.fetch_max_wait_ms,
            "statistics.interval.ms": self.statistics_interval_ms,
        }


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
    is_running: bool
    group_id: str
    client_id: str
    metrics: ConsumerMetricsSnapshot
