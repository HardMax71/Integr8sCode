from app.core.metrics.base import BaseMetrics


class IdempotencyMetrics(BaseMetrics):
    """Metrics for idempotency operations."""

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

        self.idempotency_processing_duration = self._meter.create_histogram(
            name="idempotency.processing.duration", description="Duration of idempotency checks in seconds", unit="s"
        )

        self.idempotency_keys_active = self._meter.create_up_down_counter(
            name="idempotency.keys.active", description="Number of active idempotency keys", unit="1"
        )

    def record_idempotency_cache_hit(self, event_type: str, operation: str) -> None:
        self.idempotency_cache_hits.add(1, attributes={"event_type": event_type, "operation": operation})

    def record_idempotency_cache_miss(self, event_type: str, operation: str) -> None:
        self.idempotency_cache_misses.add(1, attributes={"event_type": event_type, "operation": operation})

    def record_idempotency_duplicate_blocked(self, event_type: str) -> None:
        self.idempotency_duplicates_blocked.add(1, attributes={"event_type": event_type})

    def record_idempotency_processing_duration(self, duration_seconds: float, operation: str) -> None:
        self.idempotency_processing_duration.record(duration_seconds, attributes={"operation": operation})

    def increment_idempotency_keys(self, prefix: str) -> None:
        """Increment active idempotency keys count when a new key is created."""
        self.idempotency_keys_active.add(1, attributes={"key_prefix": prefix})

    def decrement_idempotency_keys(self, prefix: str) -> None:
        """Decrement active idempotency keys count when a key is removed."""
        self.idempotency_keys_active.add(-1, attributes={"key_prefix": prefix})

    def record_idempotent_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.idempotency_processing_duration.record(duration_seconds, attributes={"event_type": event_type})
