

import pytest

from app.core.metrics.execution import ExecutionMetrics
from app.core.metrics.events import EventMetrics
from app.domain.enums.execution import ExecutionStatus


pytestmark = pytest.mark.unit


def test_execution_metrics_methods() -> None:
    """Test with no-op metrics."""
    
    m = ExecutionMetrics()
    m.record_script_execution(ExecutionStatus.QUEUED, "python-3.11")
    m.record_execution_duration(0.5, "python-3.11")
    m.increment_active_executions(); m.decrement_active_executions()
    m.record_memory_usage(123.4, "python-3.11")
    m.record_error("timeout")
    m.update_queue_depth(1); m.update_queue_depth(-1)
    m.record_queue_wait_time(0.1, "python-3.11")
    m.record_execution_assigned(); m.record_execution_queued(); m.record_execution_scheduled("ok")
    m.update_cpu_available(100.0); m.update_memory_available(512.0); m.update_gpu_available(1)
    m.update_allocations_active(2)


def test_event_metrics_methods() -> None:
    """Test with no-op metrics."""
    
    m = EventMetrics()
    m.record_event_published("execution.requested", None)
    m.record_event_processing_duration(0.05, "execution.requested")
    m.record_pod_event_published("pod.running")
    m.record_event_replay_operation("prepare", "success")
    m.update_event_buffer_size(3)
    m.record_event_buffer_dropped(); m.record_event_buffer_processed()
    m.record_event_buffer_latency(0.2)
    m.set_event_buffer_backpressure(True); m.set_event_buffer_backpressure(False)
    m.record_event_buffer_memory_usage(12.3)
    m.record_event_stored("execution.requested", "events")
    m.record_events_processing_failed("topic", "etype", "group", "error")
    m.record_event_store_duration(0.1, "insert", "events")
    m.record_event_store_failed("etype", "fail")
    m.record_event_query_duration(0.2, "by_type", "events")
    m.record_processing_duration(0.3, "topic", "etype", "group")
    m.record_kafka_message_produced("t"); m.record_kafka_message_consumed("t", "g")
    m.record_kafka_consumer_lag(10, "t", "g", 0)
    m.record_kafka_production_error("t", "e"); m.record_kafka_consumption_error("t", "g", "e")
    m.update_event_bus_queue_size(1, "default"); m.set_event_bus_queue_size(5, "default"); m.set_event_bus_queue_size(2, "default")

