import redis
from opentelemetry.metrics import CallbackOptions, Observation

from app.core.metrics.base import BaseMetrics
from app.settings import Settings

_KEY_PATTERN = "idempotency:*"


class IdempotencyMetrics(BaseMetrics):
    """Metrics for idempotency operations."""

    def __init__(self, settings: Settings, meter_name: str | None = None) -> None:
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            ssl=settings.REDIS_SSL,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        super().__init__(settings, meter_name)

    def _create_instruments(self) -> None:
        self.idempotency_cache_hits = self._meter.create_counter(
            name="idempotency.cache.hits.total", description="Total idempotency cache hits", unit="1"
        )

        self.idempotency_cache_misses = self._meter.create_counter(
            name="idempotency.cache.misses.total", description="Total idempotency cache misses", unit="1"
        )

        self.idempotency_duplicates_blocked = self._meter.create_counter(
            name="idempotency.duplicates.blocked.total",
            description="Total duplicate operations blocked by idempotency",
            unit="1",
        )

        self.idempotency_check_duration = self._meter.create_histogram(
            name="idempotency.check.duration", description="Duration of idempotency key checks in seconds", unit="s"
        )

        self.idempotency_processing_duration = self._meter.create_histogram(
            name="idempotency.processing.duration",
            description="Time from reserving an idempotency key to marking it completed or failed, in seconds",
            unit="s",
        )

        self._meter.create_observable_gauge(
            name="idempotency.keys.active",
            callbacks=[self._observe_active_keys],
            description="Idempotency keys currently stored in Redis",
            unit="{key}",
        )

    def _observe_active_keys(self, _: CallbackOptions) -> list[Observation]:
        try:
            count = sum(1 for _ in self._redis.scan_iter(match=_KEY_PATTERN, count=1000))
        except redis.RedisError:
            return []
        return [Observation(count)]

    def record_idempotency_cache_hit(self, event_type: str, operation: str) -> None:
        self.idempotency_cache_hits.add(1, attributes={"event_type": event_type, "operation": operation})

    def record_idempotency_cache_miss(self, event_type: str, operation: str) -> None:
        self.idempotency_cache_misses.add(1, attributes={"event_type": event_type, "operation": operation})

    def record_idempotency_duplicate_blocked(self, event_type: str) -> None:
        self.idempotency_duplicates_blocked.add(1, attributes={"event_type": event_type})

    def record_idempotency_check_duration(self, duration_seconds: float, operation: str) -> None:
        self.idempotency_check_duration.record(duration_seconds, attributes={"operation": operation})

    def record_idempotent_processing_duration(self, duration_seconds: float, event_type: str, status: str) -> None:
        self.idempotency_processing_duration.record(
            duration_seconds, attributes={"event_type": event_type, "status": status}
        )
