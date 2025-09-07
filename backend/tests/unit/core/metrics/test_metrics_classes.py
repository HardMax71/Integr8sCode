from app.core.metrics.connections import ConnectionMetrics
from app.core.metrics.coordinator import CoordinatorMetrics
from app.core.metrics.database import DatabaseMetrics
from app.core.metrics.dlq import DLQMetrics
from app.core.metrics.events import EventMetrics
from app.core.metrics.execution import ExecutionMetrics
from app.core.metrics.health import HealthMetrics
from app.core.metrics.kubernetes import KubernetesMetrics
from app.core.metrics.notifications import NotificationMetrics
from app.core.metrics.rate_limit import RateLimitMetrics
from app.core.metrics.replay import ReplayMetrics
from app.core.metrics.security import SecurityMetrics


def test_connection_metrics_smoke():
    """Test ConnectionMetrics smoke test with no-op metrics."""
    # Create ConnectionMetrics instance - will use NoOpMeterProvider automatically
    m = ConnectionMetrics()
    m.increment_sse_connections("exec")
    m.decrement_sse_connections("exec")
    m.record_sse_message_sent("exec", "evt")
    m.record_sse_connection_duration(0.1, "exec")
    m.update_sse_draining_connections(1)
    m.record_sse_shutdown_duration(0.01, "notify")
    m.update_event_bus_subscribers(3, "*")


def test_event_metrics_smoke():
    """Test EventMetrics smoke test with no-op metrics."""
    # Create EventMetrics instance - will use NoOpMeterProvider automatically
    m = EventMetrics()
    m.record_event_published("execution.requested")
    m.record_event_processing_duration(0.01, "execution.requested")
    m.record_pod_event_published("pod.created")
    m.record_event_replay_operation("replay", "success")
    m.update_event_buffer_size(1)
    m.record_event_buffer_dropped()
    m.record_event_buffer_processed()
    m.record_event_buffer_latency(0.005)
    m.set_event_buffer_backpressure(True)
    m.record_event_buffer_memory_usage(1.2)
    m.record_event_stored("x", "events")
    m.record_events_processing_failed("t", "x", "g", "ValueError")
    m.record_event_store_duration(0.01, "store", "events")
    m.record_event_store_failed("x", "RuntimeError")
    m.record_event_query_duration(0.02, "by_id", "events")
    m.record_processing_duration(0.03, "t", "x", "g")
    m.record_kafka_message_produced("t")
    m.record_kafka_message_consumed("t", "g")
    m.record_kafka_consumer_lag(10, "t", "g", 0)
    m.record_kafka_production_error("t", "E")
    m.record_kafka_consumption_error("t", "g", "E")
    m.update_event_bus_queue_size(1)
    m.set_event_bus_queue_size(5)


def test_other_metrics_classes_smoke():
    """Test other metrics classes smoke test with no-op metrics."""
    # Create metrics instances - will use NoOpMeterProvider automatically
    CoordinatorMetrics().record_coordinator_processing_time(0.01)
    DatabaseMetrics().record_mongodb_operation("read", "ok")
    DLQMetrics().record_dlq_message_received("topic", "type")
    ExecutionMetrics().record_script_execution("QUEUED", "python")
    HealthMetrics().record_health_check_duration(0.001, "liveness", "basic")
    KubernetesMetrics().record_k8s_pod_created("success", "python")
    NotificationMetrics().record_notification_sent("welcome", channel="email")
    RateLimitMetrics().requests_total.add(1)
    ReplayMetrics().record_session_created("by_id", "kafka")
    SecurityMetrics().record_security_event("scan", severity="low")

