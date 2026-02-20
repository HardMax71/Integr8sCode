import pytest
from app.core.metrics import ConnectionMetrics, QueueMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_connection_metrics_methods(test_settings: Settings) -> None:
    """Test ConnectionMetrics methods with no-op metrics."""
    m = ConnectionMetrics(test_settings)
    m.increment_sse_connections("/events")
    m.decrement_sse_connections("/events")
    m.record_sse_message_sent("/events", "etype")
    m.record_sse_connection_duration(1.2, "/events")
    m.update_sse_draining_connections(1)


def test_queue_metrics_methods(test_settings: Settings) -> None:
    """Test QueueMetrics methods with no-op metrics."""
    m = QueueMetrics(test_settings)
    m.record_enqueue()
    m.record_schedule()
    m.record_release()
    m.record_wait_time(0.3, "high")
