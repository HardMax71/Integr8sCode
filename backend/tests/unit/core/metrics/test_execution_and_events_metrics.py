import pytest
from app.core.metrics import EventMetrics, ExecutionMetrics
from app.domain.enums import ExecutionStatus
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_execution_metrics_methods(test_settings: Settings) -> None:
    """Test with no-op metrics."""
    m = ExecutionMetrics(test_settings)
    m.record_script_execution(ExecutionStatus.QUEUED, "python-3.11")
    m.record_execution_duration(0.5, "python-3.11")
    m.increment_active_executions()
    m.decrement_active_executions()
    m.record_memory_usage(123.4, "python-3.11")
    m.record_error("timeout")
    m.update_queue_depth(1)
    m.update_queue_depth(-1)
    m.record_queue_wait_time(0.1, "python-3.11")
    m.record_execution_assigned()
    m.record_execution_queued()
    m.record_execution_scheduled()


def test_event_metrics_methods(test_settings: Settings) -> None:
    """Test with no-op metrics."""
    m = EventMetrics(test_settings)
    m.record_event_published("execution.requested", None)
    m.record_event_processing_duration(0.05, "execution.requested")
    m.record_events_processing_failed("topic", "etype", "group", "error")
