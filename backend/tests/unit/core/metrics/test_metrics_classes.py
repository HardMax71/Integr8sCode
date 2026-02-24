import pytest
from app.core.metrics import (
    ConnectionMetrics,
    IdempotencyMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    QueueMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.domain.enums import ExecutionStatus
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_connection_metrics_smoke(test_settings: Settings) -> None:
    """Test ConnectionMetrics smoke test with no-op metrics."""
    m = ConnectionMetrics(test_settings)
    m.increment_sse_connections("exec")
    m.decrement_sse_connections("exec")
    m.record_sse_message_sent("exec", "evt")
    m.record_sse_connection_duration(0.1, "exec")
    m.update_sse_draining_connections(1)


def test_event_metrics_smoke(test_settings: Settings) -> None:
    """Test EventMetrics smoke test with no-op metrics."""
    m = EventMetrics(test_settings)
    m.record_event_published("execution.requested")
    m.record_event_processing_duration(0.01, "execution.requested")
    m.record_event_replay_operation("replay", "success")
    m.record_event_stored("x", "events")
    m.record_events_processing_failed("t", "x", "g", "ValueError")
    m.record_event_store_duration(0.01, "store", "events")
    m.record_event_store_failed("x", "RuntimeError")
    m.record_event_query_duration(0.02, "by_id", "events")
    m.record_processing_duration(0.03, "t", "x", "g")
    m.record_kafka_message_produced("t")
    m.record_kafka_message_consumed("t", "g")
    m.record_kafka_production_error("t", "E")
    m.record_kafka_consumption_error("t", "g", "E")
    m.update_event_bus_queue_size(1)
    m.set_event_bus_queue_size(5)


def test_other_metrics_classes_smoke(test_settings: Settings) -> None:
    """Test other metrics classes smoke test with no-op metrics."""
    QueueMetrics(test_settings).record_enqueue()
    IdempotencyMetrics(test_settings).record_idempotency_cache_hit("etype", "check")
    DLQMetrics(test_settings).record_dlq_message_received("topic", "type")
    ExecutionMetrics(test_settings).record_script_execution(ExecutionStatus.QUEUED, "python")
    KubernetesMetrics(test_settings).record_k8s_pod_created("success", "python")
    NotificationMetrics(test_settings).record_notification_sent("welcome", channel="email")
    RateLimitMetrics(test_settings).record_request("/api/test", True, "sliding_window")
    ReplayMetrics(test_settings).record_session_created("by_id", "kafka")
    SecurityMetrics(test_settings).record_authentication_attempt("password", True, 0.1)
