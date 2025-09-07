from app.core.metrics.base import BaseMetrics


class DatabaseMetrics(BaseMetrics):
    """Metrics for database operations."""

    def _create_instruments(self) -> None:
        # MongoDB operation metrics
        self.mongodb_event_operations = self._meter.create_counter(
            name="mongodb.event.operations.total",
            description="Total MongoDB operations for events",
            unit="1"
        )

        self.mongodb_event_query_duration = self._meter.create_histogram(
            name="mongodb.event.query.duration",
            description="Duration of MongoDB event queries in seconds",
            unit="s"
        )

        # Event store specific metrics
        self.event_store_operations = self._meter.create_counter(
            name="event.store.operations.total",
            description="Total event store operations",
            unit="1"
        )

        self.event_store_failures = self._meter.create_counter(
            name="event.store.failures.total",
            description="Total event store operation failures",
            unit="1"
        )

        # Idempotency metrics
        self.idempotency_cache_hits = self._meter.create_counter(
            name="idempotency.cache.hits.total",
            description="Total idempotency cache hits",
            unit="1"
        )

        self.idempotency_cache_misses = self._meter.create_counter(
            name="idempotency.cache.misses.total",
            description="Total idempotency cache misses",
            unit="1"
        )

        self.idempotency_duplicates_blocked = self._meter.create_counter(
            name="idempotency.duplicates.blocked.total",
            description="Total duplicate operations blocked by idempotency",
            unit="1"
        )

        self.idempotency_processing_duration = self._meter.create_histogram(
            name="idempotency.processing.duration",
            description="Duration of idempotency checks in seconds",
            unit="s"
        )

        self.idempotency_keys_active = self._meter.create_up_down_counter(
            name="idempotency.keys.active",
            description="Number of active idempotency keys",
            unit="1"
        )

        # Database connection metrics
        self.database_connections_active = self._meter.create_up_down_counter(
            name="database.connections.active",
            description="Number of active database connections",
            unit="1"
        )

        self.database_connection_errors = self._meter.create_counter(
            name="database.connection.errors.total",
            description="Total database connection errors",
            unit="1"
        )

    def record_mongodb_operation(self, operation: str, status: str) -> None:
        self.mongodb_event_operations.add(
            1,
            attributes={
                "operation": operation,
                "status": status
            }
        )

    def record_mongodb_query_duration(self, duration_seconds: float, operation: str) -> None:
        self.mongodb_event_query_duration.record(
            duration_seconds,
            attributes={"operation": operation}
        )

    def record_event_store_duration(self, duration_seconds: float, operation: str, collection: str) -> None:
        self.mongodb_event_query_duration.record(
            duration_seconds,
            attributes={
                "operation": f"store_{operation}",
                "collection": collection
            }
        )

        # Also record in event store specific counter
        self.event_store_operations.add(
            1,
            attributes={
                "operation": operation,
                "collection": collection
            }
        )

    def record_event_query_duration(self, duration_seconds: float, operation: str, collection: str) -> None:
        self.mongodb_event_query_duration.record(
            duration_seconds,
            attributes={
                "operation": f"query_{operation}",
                "collection": collection
            }
        )

    def record_event_store_failed(self, event_type: str, error_type: str) -> None:
        self.event_store_failures.add(
            1,
            attributes={
                "event_type": event_type,
                "error_type": error_type
            }
        )

    def record_idempotency_cache_hit(self, event_type: str, operation: str) -> None:
        self.idempotency_cache_hits.add(
            1,
            attributes={
                "event_type": event_type,
                "operation": operation
            }
        )

    def record_idempotency_cache_miss(self, event_type: str, operation: str) -> None:
        self.idempotency_cache_misses.add(
            1,
            attributes={
                "event_type": event_type,
                "operation": operation
            }
        )

    def record_idempotency_duplicate_blocked(self, event_type: str) -> None:
        self.idempotency_duplicates_blocked.add(
            1,
            attributes={"event_type": event_type}
        )

    def record_idempotency_processing_duration(self, duration_seconds: float, operation: str) -> None:
        self.idempotency_processing_duration.record(
            duration_seconds,
            attributes={"operation": operation}
        )

    def update_idempotency_keys_active(self, count: int, prefix: str) -> None:
        # Track the delta for gauge-like behavior
        key = f'_idempotency_keys_{prefix}'
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.idempotency_keys_active.add(
                delta,
                attributes={"key_prefix": prefix}
            )
        setattr(self, key, count)

    def record_idempotent_event_processed(self, event_type: str, result: str) -> None:
        self.event_store_operations.add(
            1,
            attributes={
                "operation": "idempotent_process",
                "event_type": event_type,
                "result": result
            }
        )

    def record_idempotent_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.idempotency_processing_duration.record(
            duration_seconds,
            attributes={"event_type": event_type}
        )

    def update_database_connections(self, delta: int) -> None:
        self.database_connections_active.add(delta)

    def record_database_connection_error(self, error_type: str) -> None:
        self.database_connection_errors.add(
            1,
            attributes={"error_type": error_type}
        )
