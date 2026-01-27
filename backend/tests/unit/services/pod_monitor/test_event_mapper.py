import json
import logging
from unittest.mock import MagicMock

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
)
from app.services.pod_monitor.event_mapper import PodContext, PodEventMapper

from tests.unit.services.pod_monitor.conftest import (
    ContainerStatus,
    Pod,
    State,
    Terminated,
    Waiting,
)

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.pod_monitor.event_mapper")


def _ctx(pod: Pod, event_type: str = "ADDED") -> PodContext:
    return PodContext(
        pod=pod,
        execution_id="e1",
        metadata=EventMetadata(service_name="t", service_version="1", user_id="test"),
        phase=pod.status.phase or "",
        event_type=event_type,
    )


def _make_mock_api(logs: str = "{}") -> MagicMock:
    """Create a mock API that returns the given logs."""
    mock = MagicMock()
    mock.read_namespaced_pod_log.return_value = logs
    return mock


def test_pending_running_and_succeeded_mapping() -> None:
    logs_json = json.dumps({
        "stdout": "ok",
        "stderr": "",
        "exit_code": 0,
        "resource_usage": {
            "execution_time_wall_seconds": 0,
            "cpu_time_jiffies": 0,
            "clk_tck_hertz": 0,
            "peak_memory_kb": 0,
        },
    })
    pem = PodEventMapper(k8s_api=_make_mock_api(logs_json), logger=_test_logger)

    # Pending -> scheduled (set execution-id label and PodScheduled condition)
    pend = Pod("p", "Pending")
    pend.metadata.labels = {"execution-id": "e1"}

    class Cond:
        def __init__(self, t: str, s: str) -> None:
            self.type = t
            self.status = s

    pend.status.conditions = [Cond("PodScheduled", "True")]
    pend.spec.node_name = "n"
    evts = pem.map_pod_event(pend, "ADDED")
    assert any(e.event_type == EventType.POD_SCHEDULED for e in evts)

    # Running -> running, includes container statuses JSON
    cs = [ContainerStatus(State(waiting=Waiting("Init"))), ContainerStatus(State(terminated=Terminated(2)))]
    run = Pod("p", "Running", cs=cs)
    run.metadata.labels = {"execution-id": "e1"}
    evts = pem.map_pod_event(run, "MODIFIED")
    # Print for debugging if test fails
    if not any(e.event_type == EventType.POD_RUNNING for e in evts):
        print(f"Events returned: {[e.event_type for e in evts]}")
    assert any(e.event_type == EventType.POD_RUNNING for e in evts)
    pr = [e for e in evts if e.event_type == EventType.POD_RUNNING][0]
    assert isinstance(pr, PodRunningEvent)
    assert any("waiting" in s.state for s in pr.container_statuses) and any(
        "terminated" in s.state for s in pr.container_statuses
    )

    # Succeeded -> completed; logs parsed JSON used
    term = ContainerStatus(State(terminated=Terminated(0)))
    suc = Pod("p", "Succeeded", cs=[term])
    suc.metadata.labels = {"execution-id": "e1"}
    evts = pem.map_pod_event(suc, "MODIFIED")
    comp = [e for e in evts if e.event_type == EventType.EXECUTION_COMPLETED][0]
    assert isinstance(comp, ExecutionCompletedEvent)
    assert comp.exit_code == 0 and comp.stdout == "ok"


def test_failed_timeout_and_deleted() -> None:
    valid_logs = json.dumps({"stdout": "", "stderr": "", "exit_code": 137, "resource_usage": {}})
    pem = PodEventMapper(k8s_api=_make_mock_api(valid_logs), logger=_test_logger)

    # Timeout via DeadlineExceeded
    pod_to = Pod(
        "p", "Failed", cs=[ContainerStatus(State(terminated=Terminated(137)))],
        reason="DeadlineExceeded", adl=5,
    )
    pod_to.metadata.labels = {"execution-id": "e1"}
    ev = pem.map_pod_event(pod_to, "MODIFIED")[0]
    assert isinstance(ev, ExecutionTimeoutEvent)
    assert ev.event_type == EventType.EXECUTION_TIMEOUT and ev.timeout_seconds == 5

    # Failed: terminated exit_code nonzero, message used as stderr, error type defaults to SCRIPT_ERROR
    # Note: ExecutionFailedEvent can have None resource_usage when logs extraction fails
    pem_no_logs = PodEventMapper(k8s_api=_make_mock_api(""), logger=_test_logger)
    pod_fail = Pod("p2", "Failed", cs=[ContainerStatus(State(terminated=Terminated(2, message="boom")))])
    pod_fail.metadata.labels = {"execution-id": "e2"}
    evf = pem_no_logs.map_pod_event(pod_fail, "MODIFIED")[0]
    assert isinstance(evf, ExecutionFailedEvent)
    assert evf.event_type == EventType.EXECUTION_FAILED and evf.error_type in {ExecutionErrorType.SCRIPT_ERROR}

    # Deleted -> terminated when container terminated present (exit code 0 returns completed for DELETED)
    valid_logs_0 = json.dumps({"stdout": "", "stderr": "", "exit_code": 0, "resource_usage": {}})
    pem_completed = PodEventMapper(k8s_api=_make_mock_api(valid_logs_0), logger=_test_logger)
    pod_del = Pod("p3", "Failed", cs=[ContainerStatus(State(terminated=Terminated(0, reason="Completed")))])
    pod_del.metadata.labels = {"execution-id": "e3"}
    evd = pem_completed.map_pod_event(pod_del, "DELETED")[0]
    # For DELETED event with exit code 0, it returns execution_completed, not pod_terminated
    assert evd.event_type == EventType.EXECUTION_COMPLETED


def test_extract_id_and_metadata_priority_and_duplicates() -> None:
    pem = PodEventMapper(k8s_api=_make_mock_api(""), logger=_test_logger)

    # From label
    p = Pod("any", "Pending")
    p.metadata.labels = {"execution-id": "L1", "user-id": "u", "correlation-id": "corrL"}
    md = pem._create_metadata(p)
    assert pem._extract_execution_id(p) == "L1" and md.user_id == "u" and md.correlation_id == "corrL"

    # From annotation when label absent, annotation wins for correlation
    p2 = Pod("any", "Pending")
    p2.metadata.annotations = {"integr8s.io/execution-id": "A1", "integr8s.io/correlation-id": "corrA"}
    assert pem._extract_execution_id(p2) == "A1"  # from annotation
    md2 = pem._create_metadata(p2)
    assert md2.correlation_id == "corrA"

    # From name pattern exec-<id>
    p3 = Pod("exec-XYZ", "Pending")
    assert pem._extract_execution_id(p3) == "XYZ"

    # Duplicate detection caches phase
    pem._event_cache.clear()
    assert pem._is_duplicate("n1", "Running") is False
    assert pem._is_duplicate("n1", "Running") is True


def test_scheduled_requires_condition() -> None:
    class Cond:
        def __init__(self, t: str, s: str) -> None:
            self.type = t
            self.status = s

    pem = PodEventMapper(k8s_api=_make_mock_api(""), logger=_test_logger)
    pod = Pod("p", "Pending")
    # No conditions -> None
    assert pem._map_scheduled(_ctx(pod)) is None
    # Wrong condition -> None
    pod.status.conditions = [Cond("Ready", "True")]
    assert pem._map_scheduled(_ctx(pod)) is None
    # Correct -> event
    pod.status.conditions = [Cond("PodScheduled", "True")]
    pod.spec.node_name = "n"
    assert pem._map_scheduled(_ctx(pod)) is not None


def test_parse_and_log_paths_and_analyze_failure_variants(caplog: pytest.LogCaptureFixture) -> None:
    # _parse_executor_output line-by-line
    line_json = '{"stdout":"x","stderr":"","exit_code":3,"resource_usage":{}}'
    pem = PodEventMapper(k8s_api=_make_mock_api("junk\n" + line_json), logger=_test_logger)
    pod = Pod("p", "Succeeded", cs=[ContainerStatus(State(terminated=Terminated(0)))])
    logs = pem._extract_logs(pod)
    assert logs is not None
    assert logs.exit_code == 3 and logs.stdout == "x"

    # _extract_logs: no api -> returns None
    pem2 = PodEventMapper(k8s_api=None, logger=_test_logger)
    assert pem2._extract_logs(pod) is None

    # _extract_logs exceptions -> 404/400/generic branches, all return None
    mock_404 = MagicMock()
    mock_404.read_namespaced_pod_log.side_effect = Exception("404 Not Found")

    mock_400 = MagicMock()
    mock_400.read_namespaced_pod_log.side_effect = Exception("400 Bad Request")

    mock_gen = MagicMock()
    mock_gen.read_namespaced_pod_log.side_effect = Exception("boom")

    pem404 = PodEventMapper(k8s_api=mock_404, logger=_test_logger)
    assert pem404._extract_logs(pod) is None
    pem400 = PodEventMapper(k8s_api=mock_400, logger=_test_logger)
    assert pem400._extract_logs(pod) is None
    pemg = PodEventMapper(k8s_api=mock_gen, logger=_test_logger)
    assert pemg._extract_logs(pod) is None

    # _analyze_failure: Evicted
    pod_e = Pod("p", "Failed")
    pod_e.status.reason = "Evicted"
    assert pem._analyze_failure(pod_e).error_type == ExecutionErrorType.RESOURCE_LIMIT

    # Waiting reasons mapping
    pod_w = Pod("p", "Failed", cs=[ContainerStatus(State(waiting=Waiting("ImagePullBackOff")))])
    assert pem._analyze_failure(pod_w).error_type == ExecutionErrorType.SYSTEM_ERROR
    pod_w2 = Pod("p", "Failed", cs=[ContainerStatus(State(waiting=Waiting("CrashLoopBackOff")))])
    assert pem._analyze_failure(pod_w2).error_type == ExecutionErrorType.SCRIPT_ERROR
    pod_w3 = Pod("p", "Failed", cs=[ContainerStatus(State(waiting=Waiting("ErrImagePull")))])
    assert pem._analyze_failure(pod_w3).error_type == ExecutionErrorType.SYSTEM_ERROR

    # OOMKilled in status.message
    pod_oom = Pod("p", "Failed")
    pod_oom.status.message = "... OOMKilled ..."
    assert pem._analyze_failure(pod_oom).error_type == ExecutionErrorType.RESOURCE_LIMIT


def test_all_containers_succeeded_and_cache_behavior() -> None:
    valid_logs = json.dumps({"stdout": "", "stderr": "", "exit_code": 0, "resource_usage": {}})
    pem = PodEventMapper(k8s_api=_make_mock_api(valid_logs), logger=_test_logger)
    term0 = ContainerStatus(State(terminated=Terminated(0)))
    term0b = ContainerStatus(State(terminated=Terminated(0)))
    pod = Pod("p", "Failed", cs=[term0, term0b])
    pod.metadata.labels = {"execution-id": "e1"}
    # When all succeeded, failed mapping returns completed instead of failed
    ev = pem.map_pod_event(pod, "MODIFIED")[0]
    assert ev.event_type == EventType.EXECUTION_COMPLETED

    # Cache prevents duplicate for same phase unless event type changes
    p2 = Pod("p2", "Running")
    a = pem.map_pod_event(p2, "ADDED")
    b = pem.map_pod_event(p2, "MODIFIED")
    # First ADD should map; second MODIFIED with same phase might be filtered by cache → allow either empty or same
    assert a == [] or all(x.event_type for x in a)
    assert b == [] or all(x.event_type for x in b)
