import pytest
from app.core.metrics import ConnectionMetrics, CoordinatorMetrics
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


def test_coordinator_metrics_methods(test_settings: Settings) -> None:
    """Test CoordinatorMetrics methods with no-op metrics."""
    m = CoordinatorMetrics(test_settings)
    m.record_coordinator_scheduling_duration(0.4)
    m.update_coordinator_active_executions(3)
    m.update_coordinator_active_executions(1)
    m.record_coordinator_queue_time(0.3, "high")
    m.record_coordinator_execution_scheduled("ok")
    m.update_execution_request_queue_size(10)
    m.update_execution_request_queue_size(6)
