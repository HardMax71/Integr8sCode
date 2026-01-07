import pytest
from app.core.metrics.database import DatabaseMetrics
from app.core.metrics.dlq import DLQMetrics

pytestmark = pytest.mark.unit


def test_database_metrics_methods() -> None:
    """Test DatabaseMetrics methods with no-op metrics."""
    # Create DatabaseMetrics instance - will use NoOpMeterProvider automatically
    m = DatabaseMetrics()
    m.record_mongodb_operation("insert", "ok")
    m.record_mongodb_query_duration(0.1, "find")
    m.record_event_store_duration(0.2, "insert", "events")
    m.record_event_query_duration(0.3, "by_type", "events")
    m.record_event_store_failed("etype", "error")
    m.record_idempotency_cache_hit("etype", "check")
    m.record_idempotency_cache_miss("etype", "check")
    m.record_idempotency_duplicate_blocked("etype")
    m.record_idempotency_processing_duration(0.4, "process")
    m.update_idempotency_keys_active(10, "prefix")
    m.update_idempotency_keys_active(5, "prefix")
    m.record_idempotent_event_processed("etype", "blocked")
    m.record_idempotent_processing_duration(0.5, "etype")
    m.update_database_connections(1)
    m.update_database_connections(-1)
    m.record_database_connection_error("timeout")


def test_dlq_metrics_methods() -> None:
    """Test DLQMetrics methods with no-op metrics."""
    # Create DLQMetrics instance - will use NoOpMeterProvider automatically
    m = DLQMetrics()
    m.record_dlq_message_received("topic", "etype")
    m.record_dlq_message_retried("topic", "etype", "success")
    m.record_dlq_message_discarded("topic", "etype", "bad")
    m.record_dlq_processing_duration(0.1, "parse")
    m.update_dlq_queue_size("topic", 10)
    m.update_dlq_queue_size("topic", 7)
    m.record_dlq_message_age(5.0)
    m.record_dlq_retry_attempt("topic", "etype", 2)
    m.record_dlq_processing_error("topic", "etype", "err")
    m.record_dlq_throughput(12.0, "topic")
    m.increment_dlq_queue_size("topic")
    m.decrement_dlq_queue_size("topic")
