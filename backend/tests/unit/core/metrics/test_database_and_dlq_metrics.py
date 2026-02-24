import pytest
from app.core.metrics import IdempotencyMetrics, DLQMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_idempotency_metrics_methods(test_settings: Settings) -> None:
    """Test IdempotencyMetrics methods with no-op metrics."""
    m = IdempotencyMetrics(test_settings)
    m.record_idempotency_cache_hit("etype", "check")
    m.record_idempotency_cache_miss("etype", "check")
    m.record_idempotency_duplicate_blocked("etype")
    m.record_idempotency_processing_duration(0.4, "process")
    m.increment_idempotency_keys("prefix")
    m.decrement_idempotency_keys("prefix")
    m.record_idempotent_processing_duration(0.5, "etype")


def test_dlq_metrics_methods(test_settings: Settings) -> None:
    """Test DLQMetrics methods with no-op metrics."""
    m = DLQMetrics(test_settings)
    m.record_dlq_message_received("topic", "etype")
    m.record_dlq_message_retried("topic", "etype", "success")
    m.record_dlq_message_discarded("topic", "etype", "bad")
    m.record_dlq_processing_duration(0.1, "parse")
    m.update_dlq_queue_size("topic", 10)
    m.update_dlq_queue_size("topic", 7)
    m.record_dlq_message_age(5.0)
    m.record_dlq_processing_error("topic", "etype", "err")
