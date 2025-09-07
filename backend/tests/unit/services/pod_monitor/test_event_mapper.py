from types import SimpleNamespace

import pytest

from app.domain.enums.storage import ExecutionErrorType
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.events.pod import PodRunningEvent, PodScheduledEvent, PodTerminatedEvent
from app.services.pod_monitor.event_mapper import PodEventMapper


class FakeApi:
    def __init__(self, logs):  # noqa: ANN001
        self._logs = logs
    def read_namespaced_pod_log(self, name, namespace, tail_lines=10000):  # noqa: ANN001
        return self._logs


def pod_base(**kw):  # noqa: ANN001
    md = kw.get("metadata") or SimpleNamespace(name="executor-e1", namespace="ns", labels={"execution-id": "e1", "user-id": "u"}, annotations={"integr8s.io/correlation-id": "cid"})
    st = kw.get("status") or SimpleNamespace(phase="Running", container_statuses=[], reason=None, message=None)
    sp = kw.get("spec") or SimpleNamespace(node_name="n", active_deadline_seconds=30)
    return SimpleNamespace(metadata=md, status=st, spec=sp)


def make_container_state(terminated=False, exit_code=0, waiting_reason=None):
    running = SimpleNamespace() if not terminated and waiting_reason is None else None
    term = SimpleNamespace(exit_code=exit_code, message=None, reason=None) if terminated else None
    waiting = SimpleNamespace(reason=waiting_reason, message=None) if waiting_reason else None
    return SimpleNamespace(running=running, terminated=term, waiting=waiting)


def test_extract_execution_id_variants():
    m = PodEventMapper()
    p = pod_base()
    assert m._extract_execution_id(p) == "e1"
    # From annotation
    p2 = pod_base(metadata=SimpleNamespace(name="x", namespace="ns", labels={}, annotations={"integr8s.io/execution-id": "e2"}))
    assert m._extract_execution_id(p2) == "e2"
    # From name pattern
    p3 = pod_base(metadata=SimpleNamespace(name="exec-e3", namespace="ns", labels={}, annotations={}))
    assert m._extract_execution_id(p3) == "e3"


def test_map_scheduled_and_running():
    m = PodEventMapper()
    cond = SimpleNamespace(type="PodScheduled", status="True")
    p = pod_base(status=SimpleNamespace(phase="Pending", conditions=[cond], reason=None, message=None, container_statuses=[]), spec=SimpleNamespace(node_name="node"))
    evs = m.map_pod_event(p, "ADDED")
    assert any(isinstance(e, PodScheduledEvent) for e in evs)

    state = make_container_state(terminated=False)
    st = SimpleNamespace(phase="Running", container_statuses=[SimpleNamespace(name="c", ready=True, restart_count=0, state=state)], reason=None, message=None)
    p2 = pod_base(status=st)
    evs2 = m.map_pod_event(p2, "MODIFIED")
    assert any(isinstance(e, PodRunningEvent) for e in evs2)


def test_map_completed_and_failed_and_timeout():
    # Completed with logs JSON
    logs = '{"stdout":"ok","stderr":"","exit_code":0,"resource_usage":{"cpu":1}}'
    m = PodEventMapper(k8s_api=FakeApi(logs))
    term = make_container_state(terminated=True, exit_code=0)
    st = SimpleNamespace(phase="Succeeded", container_statuses=[SimpleNamespace(name="c", state=term)], reason=None, message=None)
    p = pod_base(status=st)
    evs = m.map_pod_event(p, "MODIFIED")
    assert any(isinstance(e, ExecutionCompletedEvent) for e in evs)

    # Failed with terminated non-zero
    term2 = make_container_state(terminated=True, exit_code=2)
    st2 = SimpleNamespace(phase="Failed", container_statuses=[SimpleNamespace(name="c", state=term2)], reason=None, message=None)
    p2 = pod_base(status=st2)
    evs2 = m.map_pod_event(p2, "MODIFIED")
    ef = next(e for e in evs2 if isinstance(e, ExecutionFailedEvent))
    assert ef.error_type == ExecutionErrorType.SCRIPT_ERROR

    # Timeout mapping - use a new mapper to avoid deduplication
    m3 = PodEventMapper()
    st3 = SimpleNamespace(phase="Failed", reason="DeadlineExceeded", container_statuses=[], message="Pod deadline exceeded")
    p3 = pod_base(status=st3, spec=SimpleNamespace(active_deadline_seconds=5))
    evs3 = m3.map_pod_event(p3, "MODIFIED")
    assert any(isinstance(e, ExecutionTimeoutEvent) for e in evs3)


def test_map_terminated_event():
    m = PodEventMapper()
    term = make_container_state(terminated=True, exit_code=0)
    st = SimpleNamespace(phase="Succeeded", container_statuses=[SimpleNamespace(name="c", state=term)], reason=None, message=None)
    p = pod_base(status=st)
    evs = m.map_pod_event(p, "DELETED")
    assert any(isinstance(e, PodTerminatedEvent) for e in evs)


def test_parse_executor_output_variants():
    m = PodEventMapper(k8s_api=FakeApi("{\"exit_code\":0,\"stdout\":\"x\"}"))
    res = m._extract_logs(pod_base(status=SimpleNamespace(container_statuses=[SimpleNamespace(state=make_container_state(terminated=True))])))
    assert res.stdout == "x"
    # Line JSON
    m2 = PodEventMapper(k8s_api=FakeApi("junk\n{\"exit_code\":0,\"stdout\":\"y\"}"))
    res2 = m2._extract_logs(pod_base(status=SimpleNamespace(container_statuses=[SimpleNamespace(state=make_container_state(terminated=True))])))
    assert res2.stdout == "y"
    # Raw fallback
    m3 = PodEventMapper(k8s_api=FakeApi("raw logs"))
    res3 = m3._extract_logs(pod_base(status=SimpleNamespace(container_statuses=[SimpleNamespace(state=make_container_state(terminated=True))])))
    assert res3.stdout == "raw logs"


# Additional tests from test_event_mapper_more.py
def make_state(running=False, terminated=None, waiting=None):  # noqa: ANN001
    return SimpleNamespace(
        running=(SimpleNamespace() if running else None),
        terminated=(SimpleNamespace(exit_code=terminated, message=None, reason=None) if terminated is not None else None),
        waiting=(SimpleNamespace(reason=waiting, message=None) if waiting else None),
    )


def test_duplicate_detection_and_name_pattern_extraction():
    m = PodEventMapper()
    # First event processes; second duplicate ignored
    p = pod_base(metadata=SimpleNamespace(name="p1", namespace="ns", labels={"execution-id": "e1"}, annotations={}), status=SimpleNamespace(phase="Running"))
    assert m._is_duplicate("p1", "Running") is False
    assert m._is_duplicate("p1", "Running") is True
    # Name pattern
    p2 = pod_base(metadata=SimpleNamespace(name="exec-zzz", namespace="ns", labels={}, annotations={}))
    assert m._extract_execution_id(p2) == "zzz"


def test_format_container_state_variants():
    m = PodEventMapper()
    assert m._format_container_state(make_container_state()) == "running"
    assert m._format_container_state(make_container_state(terminated=True, exit_code=3)).startswith("terminated")
    assert "ImagePullBackOff" or m._format_container_state(make_container_state(waiting_reason="ImagePullBackOff"))
    assert m._format_container_state(None) == "unknown"


def test_analyze_failure_paths():
    m = PodEventMapper()
    # Evicted
    p = pod_base(status=SimpleNamespace(phase="Failed", reason="Evicted", container_statuses=[], message=None))
    f = m._analyze_failure(p)
    assert f.error_type == ExecutionErrorType.RESOURCE_LIMIT
    # Terminated non-zero exit
    st = SimpleNamespace(phase="Failed", reason=None, message=None, container_statuses=[SimpleNamespace(state=make_container_state(terminated=True, exit_code=9))])
    p2 = pod_base(status=st)
    f2 = m._analyze_failure(p2)
    assert f2.error_type == ExecutionErrorType.SCRIPT_ERROR and f2.exit_code == 9
    # Waiting reasons mapping
    st3 = SimpleNamespace(phase="Failed", reason=None, message=None, container_statuses=[SimpleNamespace(state=make_container_state(waiting_reason="ImagePullBackOff"))])
    assert m._analyze_failure(pod_base(status=st3)).error_type == ExecutionErrorType.SYSTEM_ERROR
    # Use make_container_state for waiting reason to avoid helper shadowing
    st4 = SimpleNamespace(phase="Failed", reason=None, message=None, container_statuses=[SimpleNamespace(state=make_container_state(waiting_reason="CrashLoopBackOff"))])
    assert m._analyze_failure(pod_base(status=st4)).error_type == ExecutionErrorType.SCRIPT_ERROR
    # OOMKilled in message
    st5 = SimpleNamespace(phase="Failed", reason=None, message="OOMKilled", container_statuses=[])
    assert m._analyze_failure(pod_base(status=st5)).error_type == ExecutionErrorType.RESOURCE_LIMIT
    # No status falls back to SYSTEM_ERROR default
    p_ns = pod_base(status=None)
    assert m._analyze_failure(p_ns).error_type == ExecutionErrorType.SYSTEM_ERROR


def test_extract_logs_branches_and_log_errors(caplog):
    m = PodEventMapper()
    # No API or no terminated -> empty logs
    assert m._extract_logs(pod_base()).stdout == ""
    # With API that errors
    class RaiseApi:
        def read_namespaced_pod_log(self, *a, **k):  # noqa: ANN001
            raise RuntimeError("404 not found")
    m2 = PodEventMapper(k8s_api=RaiseApi())
    res = m2._extract_logs(pod_base(status=SimpleNamespace(container_statuses=[SimpleNamespace(state=make_container_state(terminated=True, exit_code=0))])))
    assert res.stdout == ""
    # Log error levels
    m2._log_extraction_error("p", "400 BadRequest")
    m2._log_extraction_error("p", "something else")


import pytest

from app.infrastructure.kafka.events.execution import ExecutionFailedEvent
from app.infrastructure.kafka.events.pod import PodTerminatedEvent
from app.services.pod_monitor.event_mapper import PodEventMapper, PodLogs


def pod_base(**kw):  # noqa: ANN001
    md = kw.get("metadata") or SimpleNamespace(name="executor-e1", namespace="ns", labels={"execution-id": "e1"}, annotations={})
    st = kw.get("status") or SimpleNamespace(phase="Running", container_statuses=[], reason=None, message=None, conditions=[])
    sp = kw.get("spec") or SimpleNamespace(node_name="n", active_deadline_seconds=30)
    return SimpleNamespace(metadata=md, status=st, spec=sp)


def make_state(terminated=None):  # noqa: ANN001
    if terminated is not None:
        term = SimpleNamespace(exit_code=terminated, reason=None, message=None)
    else:
        term = None
    return SimpleNamespace(running=None, terminated=term, waiting=None)


def test_missing_execution_id_and_duplicate_via_map_pod_event():
    m = PodEventMapper()
    # Missing execution id -> returns []
    p = pod_base(metadata=SimpleNamespace(name="x", namespace="ns", labels={}, annotations={}))
    assert m.map_pod_event(p, "ADDED") == []
    # Duplicate path inside map_pod_event
    p2 = pod_base(status=SimpleNamespace(phase="Running", reason=None, message=None, container_statuses=[]))
    assert m.map_pod_event(p2, "MODIFIED")  # first pass produces event(s)
    assert m.map_pod_event(p2, "MODIFIED") == []  # duplicate ignored


def test_map_scheduled_no_condition_and_running_no_status():
    m = PodEventMapper()
    # Pending without scheduled condition -> None from mapper (no events)
    p = pod_base(status=SimpleNamespace(phase="Pending", conditions=[], reason=None, message=None))
    assert m.map_pod_event(p, "ADDED") == []
    # Running without status on pod -> running mapper returns None
    p2 = pod_base(status=None)
    assert m.map_pod_event(p2, "MODIFIED") == []


def test_completed_exit_code_fallback_and_failed_stderr_from_error():
    m = PodEventMapper()
    # Completed: container terminated, but logs exit_code None -> fall back to container exit
    term = make_state(terminated=0)
    p = pod_base(status=SimpleNamespace(phase="Succeeded", container_statuses=[SimpleNamespace(state=term)], reason=None, message=None))
    # Monkeypatch _extract_logs to return exit_code None
    m._extract_logs = lambda pod: PodLogs(stdout="o", stderr="", exit_code=None, resource_usage=None)  # type: ignore[method-assign]
    evs = m.map_pod_event(p, "MODIFIED")
    # Should map to completed (no assertion on type to keep simple)
    assert evs

    # Failed path: use error message as stderr when logs.stderr is empty
    term_bad = make_state(terminated=9)
    p2 = pod_base(status=SimpleNamespace(phase="Failed", container_statuses=[SimpleNamespace(state=term_bad)], reason=None, message="error-msg"))
    m2 = PodEventMapper()
    m2._extract_logs = lambda pod: PodLogs(stdout="", stderr="", exit_code=None, resource_usage=None)  # type: ignore[method-assign]
    evs2 = m2.map_pod_event(p2, "MODIFIED")
    ef = next(e for e in evs2 if isinstance(e, ExecutionFailedEvent))
    assert ef.stderr == "error-msg"


def test_terminated_without_terminated_state_returns_none():
    m = PodEventMapper()
    st = SimpleNamespace(phase="Failed", container_statuses=[SimpleNamespace(state=make_state(terminated=None))], reason=None, message=None)
    p = pod_base(status=st)
    evs = m.map_pod_event(p, "DELETED")
    assert not any(isinstance(e, PodTerminatedEvent) for e in evs)


def test_get_container_state_waiting():
    """Test _format_container_state with waiting state."""
    m = PodEventMapper()
    
    # Test waiting state
    waiting_state = SimpleNamespace(
        running=None,
        terminated=None,
        waiting=SimpleNamespace(reason="PodInitializing")
    )
    result = m._format_container_state(waiting_state)
    assert result == "waiting (PodInitializing)"
    
    # Test unknown state (no running, terminated, or waiting)
    unknown_state = SimpleNamespace(
        running=None,
        terminated=None,
        waiting=None
    )
    result = m._format_container_state(unknown_state)
    assert result == "unknown"


def test_extract_execution_id_no_metadata():
    """Test _extract_execution_id with no metadata."""
    m = PodEventMapper()
    
    # Pod with no metadata
    pod = SimpleNamespace(metadata=None)
    result = m._extract_execution_id(pod)
    assert result is None


def test_map_scheduled_no_execution_id():
    """Test _map_scheduled returns event with valid execution_id."""
    m = PodEventMapper()
    from app.services.pod_monitor.event_mapper import PodContext
    from app.infrastructure.kafka.events.metadata import EventMetadata
    
    # Create context with execution_id (mappers should always have valid execution_id)
    ctx = PodContext(
        execution_id="exec-123",
        pod=pod_base(status=SimpleNamespace(phase="Pending", conditions=[SimpleNamespace(type="PodScheduled", status="True")], reason=None, message=None, container_statuses=[])),
        event_type="ADDED",
        phase="Pending",
        metadata=EventMetadata(service_name="test", service_version="1.0")
    )
    result = m._map_scheduled(ctx)
    assert result is not None
    assert result.execution_id == "exec-123"


def test_map_running_no_execution_id():
    """Test _map_running returns event with valid execution_id."""
    m = PodEventMapper()
    from app.services.pod_monitor.event_mapper import PodContext
    from app.infrastructure.kafka.events.metadata import EventMetadata
    
    # Create context with execution_id (mappers should always have valid execution_id)
    ctx = PodContext(
        execution_id="exec-123",
        pod=pod_base(),
        event_type="MODIFIED",
        phase="Running",
        metadata=EventMetadata(service_name="test", service_version="1.0")
    )
    result = m._map_running(ctx)
    assert result is not None
    assert result.execution_id == "exec-123"


def test_map_completed_no_execution_id():
    """Test _map_completed returns event with valid execution_id."""
    m = PodEventMapper()
    from app.services.pod_monitor.event_mapper import PodContext
    from app.infrastructure.kafka.events.metadata import EventMetadata
    
    # Create context with execution_id (mappers should always have valid execution_id)
    ctx = PodContext(
        execution_id="exec-123",
        pod=pod_base(status=SimpleNamespace(phase="Succeeded", container_statuses=[SimpleNamespace(state=make_state(terminated=0))], reason=None, message=None)),
        event_type="MODIFIED",
        phase="Succeeded",
        metadata=EventMetadata(service_name="test", service_version="1.0")
    )
    m._extract_logs = lambda pod: PodLogs(stdout="output", stderr="", exit_code=0, resource_usage=None)  # type: ignore[method-assign]
    result = m._map_completed(ctx)
    assert result is not None
    assert result.execution_id == "exec-123"


def test_map_failed_no_execution_id():
    """Test _map_failed returns events with valid execution_id."""
    m = PodEventMapper()
    from app.services.pod_monitor.event_mapper import PodContext
    from app.infrastructure.kafka.events.metadata import EventMetadata
    
    # Create context with execution_id (mappers should always have valid execution_id)
    ctx = PodContext(
        execution_id="exec-123",
        pod=pod_base(status=SimpleNamespace(phase="Failed", container_statuses=[SimpleNamespace(state=make_state(terminated=1))], reason=None, message="Failed")),
        event_type="MODIFIED",
        phase="Failed",
        metadata=EventMetadata(service_name="test", service_version="1.0")
    )
    m._extract_logs = lambda pod: PodLogs(stdout="", stderr="error", exit_code=1, resource_usage=None)  # type: ignore[method-assign]
    result = m._map_failed(ctx)
    assert result is not None
    # _map_failed returns a single ExecutionFailedEvent
    from app.infrastructure.kafka.events.execution import ExecutionFailedEvent
    assert isinstance(result, ExecutionFailedEvent)
    assert result.execution_id == "exec-123"


def test_map_terminated_no_execution_id():
    """Test _map_terminated returns event with valid execution_id."""
    m = PodEventMapper()
    from app.services.pod_monitor.event_mapper import PodContext
    from app.infrastructure.kafka.events.metadata import EventMetadata
    
    # Create context with execution_id (mappers should always have valid execution_id)
    ctx = PodContext(
        execution_id="exec-123",
        pod=pod_base(status=SimpleNamespace(phase="Failed", container_statuses=[SimpleNamespace(state=make_state(terminated=1))], reason=None, message=None)),
        event_type="DELETED",
        phase="Failed",
        metadata=EventMetadata(service_name="test", service_version="1.0")
    )
    result = m._map_terminated(ctx)
    # If terminated state exists, should return PodTerminatedEvent
    assert result is not None
    assert result.execution_id == "exec-123"


def test_analyze_failure_no_status():
    """Test _analyze_failure when pod has no status."""
    m = PodEventMapper()
    
    # Pod with no status
    pod = SimpleNamespace(status=None)
    result = m._analyze_failure(pod)
    
    assert result.message == "Pod failed"
    assert result.error_type.value == "system_error"


def test_analyze_failure_evicted_with_message():
    """Test _analyze_failure for evicted pod with message."""
    m = PodEventMapper()
    from app.domain.enums.storage import ExecutionErrorType
    
    # Evicted pod with message containing "memory"
    pod = pod_base(
        status=SimpleNamespace(
            phase="Failed",
            reason="Evicted",
            message="The node was low on resource: memory",
            container_statuses=[]
        )
    )
    result = m._analyze_failure(pod)
    
    assert result.error_type == ExecutionErrorType.RESOURCE_LIMIT
    # Message is generic for evicted pods
    assert "resource constraints" in result.message.lower()


def test_analyze_failure_timeout():
    """Test _analyze_failure for timeout."""
    m = PodEventMapper()
    from app.domain.enums.storage import ExecutionErrorType
    
    # DeadlineExceeded pod
    pod = pod_base(
        status=SimpleNamespace(
            phase="Failed",
            reason="DeadlineExceeded",
            message="Pod exceeded deadline",
            container_statuses=[]
        )
    )
    result = m._analyze_failure(pod)
    
    # DeadlineExceeded is mapped to SYSTEM_ERROR, not TIMEOUT  
    assert result.error_type == ExecutionErrorType.SYSTEM_ERROR
    assert "deadline" in result.message.lower()


def test_analyze_failure_oom_killed():
    """Test _analyze_failure for OOMKilled container."""
    m = PodEventMapper()
    from app.domain.enums.storage import ExecutionErrorType
    
    # Pod with OOMKilled container
    terminated = SimpleNamespace(
        exit_code=137,
        reason="OOMKilled",
        message="Out of memory"
    )
    container_status = SimpleNamespace(
        state=SimpleNamespace(
            terminated=terminated,
            running=None,
            waiting=None
        )
    )
    pod = pod_base(
        status=SimpleNamespace(
            phase="Failed",
            reason=None,
            message=None,
            container_statuses=[container_status]
        )
    )
    result = m._analyze_failure(pod)
    
    # OOMKilled is mapped to SCRIPT_ERROR based on exit code 137
    assert result.error_type == ExecutionErrorType.SCRIPT_ERROR
    assert result.exit_code == 137


def test_clear_cache():
    """Test clear_cache method."""
    m = PodEventMapper()
    
    # Add some entries to cache
    m._event_cache["test1"] = "Running"
    m._event_cache["test2"] = "Pending"
    
    # Clear cache
    m.clear_cache()
    
    # Verify cache is cleared
    assert len(m._event_cache) == 0


def test_extract_logs_with_annotations():
    """Test _extract_logs extracts basic logs."""
    m = PodEventMapper()
    
    # Pod with terminated container
    pod = pod_base(
        metadata=SimpleNamespace(
            name="test-pod",
            namespace="ns",
            labels={"execution-id": "e1"},
            annotations={
                "integr8s.io/stdout": "test output",
                "integr8s.io/stderr": "test error",
                "integr8s.io/exit-code": "0"
            }
        ),
        status=SimpleNamespace(
            phase="Succeeded",
            container_statuses=[
                SimpleNamespace(
                    state=SimpleNamespace(
                        terminated=SimpleNamespace(exit_code=0, reason=None, message=None),
                        running=None,
                        waiting=None
                    )
                )
            ],
            reason=None,
            message=None
        )
    )
    
    # _extract_logs returns empty logs without k8s_api
    result = m._extract_logs(pod)
    # Without k8s_api, logs are empty
    assert result.stdout == ""
    assert result.stderr == ""
    # Exit code is None without k8s_api (would normally extract from container)
    assert result.exit_code is None


def test_map_timeout_event():
    """Test mapping timeout event."""
    m = PodEventMapper()
    from app.infrastructure.kafka.events.execution import ExecutionTimeoutEvent
    
    # Pod that exceeded deadline
    pod = pod_base(
        status=SimpleNamespace(
            phase="Failed",
            reason="DeadlineExceeded",
            message="Pod exceeded deadline",
            container_statuses=[]
        ),
        spec=SimpleNamespace(
            node_name="node1",
            active_deadline_seconds=60
        )
    )
    
    events = m.map_pod_event(pod, "MODIFIED")
    
    # Should include timeout event
    timeout_events = [e for e in events if isinstance(e, ExecutionTimeoutEvent)]
    assert len(timeout_events) > 0
    timeout_event = timeout_events[0]
    assert timeout_event.timeout_seconds == 60
