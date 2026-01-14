import pytest
from app.core.metrics.connections import ConnectionMetrics
from app.core.metrics.coordinator import CoordinatorMetrics
from app.domain.enums import ResourceType
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
    m.record_sse_shutdown_duration(0.5, "phase1")
    m.update_sse_shutdown_duration(0.6, "phase2")
    m.increment_event_bus_subscriptions()
    m.decrement_event_bus_subscriptions(1)
    m.update_event_bus_subscribers(3, "*")


def test_coordinator_metrics_methods(test_settings: Settings) -> None:
    """Test CoordinatorMetrics methods with no-op metrics."""
    m = CoordinatorMetrics(test_settings)
    m.record_coordinator_processing_time(0.1)
    m.record_scheduling_duration(0.2)
    m.update_active_executions_gauge(2)
    m.update_active_executions_gauge(1)
    m.record_coordinator_queue_time(0.3, "high")
    m.record_coordinator_execution_scheduled("ok")
    m.record_coordinator_scheduling_duration(0.4)
    m.update_coordinator_active_executions(3)
    m.record_queue_wait_time_by_priority(0.5, "low", "q")
    m.update_execution_request_queue_size(10)
    m.update_execution_request_queue_size(6)
    m.record_rate_limited("per_user", "u1")
    m.update_rate_limit_wait_time("per_user", "u1", 1.0)
    m.record_resource_allocation(ResourceType.CPU, 1.0, "e1")
    m.record_resource_release(ResourceType.CPU, 0.5, "e1")
    m.update_resource_usage(ResourceType.CPU, 75.0)
    m.record_scheduling_decision("assign", "enough_resources")
    m.record_queue_reordering("q", 2)
    m.record_priority_change("e1", "low", "high")
    m.update_rate_limiter_tokens("per_user", 5)
    m.record_rate_limit_reset("per_user", "u1")
