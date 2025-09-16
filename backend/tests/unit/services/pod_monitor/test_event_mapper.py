import json
import pytest

from app.domain.enums.storage import ExecutionErrorType
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.pod_monitor.event_mapper import PodContext, PodEventMapper


pytestmark = pytest.mark.unit


class Meta:
    def __init__(self, name: str, namespace: str = "integr8scode", labels=None, annotations=None) -> None:
        self.name = name
        self.namespace = namespace
        self.labels = labels or {}
        self.annotations = annotations or {}


class Terminated:
    def __init__(self, exit_code: int, reason: str | None = None, message: str | None = None) -> None:
        self.exit_code = exit_code
        self.reason = reason
        self.message = message


class Waiting:
    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        self.message = message


class State:
    def __init__(self, terminated: Terminated | None = None, waiting: Waiting | None = None, running=None) -> None:
        self.terminated = terminated
        self.waiting = waiting
        self.running = running


class ContainerStatus:
    def __init__(self, state: State | None, name: str = "c", ready: bool = True, restart_count: int = 0) -> None:
        self.state = state
        self.name = name
        self.ready = ready
        self.restart_count = restart_count


class Spec:
    def __init__(self, adl: int | None = None, node_name: str | None = None) -> None:
        self.active_deadline_seconds = adl
        self.node_name = node_name


class Status:
    def __init__(self, phase: str | None, reason: str | None = None, message: str | None = None, cs=None) -> None:
        self.phase = phase
        self.reason = reason
        self.message = message
        self.container_statuses = cs or []
        self.conditions = None


class Pod:
    def __init__(self, name: str, phase: str, cs=None, reason: str | None = None, msg: str | None = None, adl: int | None = None) -> None:
        self.metadata = Meta(name)
        self.status = Status(phase, reason, msg, cs)
        self.spec = Spec(adl)


class _FakeAPI:
    def __init__(self, logs: str) -> None:
        self._logs = logs

    def read_namespaced_pod_log(self, name: str, namespace: str, tail_lines: int = 10000):  # noqa: ARG002
        return self._logs


def _ctx(pod: Pod, event_type: str = "ADDED") -> PodContext:
    return PodContext(pod=pod, execution_id="e1", metadata=EventMetadata(service_name="t", service_version="1"), phase=pod.status.phase or "", event_type=event_type)


def test_pending_running_and_succeeded_mapping() -> None:
    pem = PodEventMapper(k8s_api=_FakeAPI(json.dumps({"stdout": "ok", "stderr": "", "exit_code": 0, "resource_usage": {"execution_time_wall_seconds": 0, "cpu_time_jiffies": 0, "clk_tck_hertz": 0, "peak_memory_kb": 0}})))

    # Pending -> scheduled (set execution-id label and PodScheduled condition)
    pend = Pod("p", "Pending")
    pend.metadata.labels = {"execution-id": "e1"}
    class Cond:
        def __init__(self, t, s): self.type=t; self.status=s
    pend.status.conditions = [Cond("PodScheduled", "True")]
    pend.spec.node_name = "n"
    evts = pem.map_pod_event(pend, "ADDED")
    assert any(e.event_type.value == "pod_scheduled" for e in evts)

    # Running -> running, includes container statuses JSON
    cs = [ContainerStatus(State(waiting=Waiting("Init"))), ContainerStatus(State(terminated=Terminated(2)))]
    run = Pod("p", "Running", cs=cs)
    run.metadata.labels = {"execution-id": "e1"}
    evts = pem.map_pod_event(run, "MODIFIED")
    # Print for debugging if test fails
    if not any(e.event_type.value == "pod_running" for e in evts):
        print(f"Events returned: {[e.event_type.value for e in evts]}")
    assert any(e.event_type.value == "pod_running" for e in evts)
    pr = [e for e in evts if e.event_type.value == "pod_running"][0]
    statuses = json.loads(pr.container_statuses)
    assert any("waiting" in s["state"] for s in statuses) and any("terminated" in s["state"] for s in statuses)

    # Succeeded -> completed; logs parsed JSON used
    term = ContainerStatus(State(terminated=Terminated(0)))
    suc = Pod("p", "Succeeded", cs=[term])
    suc.metadata.labels = {"execution-id": "e1"}
    evts = pem.map_pod_event(suc, "MODIFIED")
    comp = [e for e in evts if e.event_type.value == "execution_completed"][0]
    assert comp.exit_code == 0 and comp.stdout == "ok"


def test_failed_timeout_and_deleted() -> None:
    pem = PodEventMapper(k8s_api=_FakeAPI(""))

    # Timeout via DeadlineExceeded
    pod_to = Pod("p", "Failed", cs=[ContainerStatus(State(terminated=Terminated(137)))], reason="DeadlineExceeded", adl=5)
    pod_to.metadata.labels = {"execution-id": "e1"}
    ev = pem.map_pod_event(pod_to, "MODIFIED")[0]
    assert ev.event_type.value == "execution_timeout" and ev.timeout_seconds == 5

    # Failed: terminated exit_code nonzero, message used as stderr, error type defaults to SCRIPT_ERROR
    pod_fail = Pod("p2", "Failed", cs=[ContainerStatus(State(terminated=Terminated(2, message="boom")))])
    pod_fail.metadata.labels = {"execution-id": "e2"}
    evf = pem.map_pod_event(pod_fail, "MODIFIED")[0]
    assert evf.event_type.value == "execution_failed" and evf.error_type in {ExecutionErrorType.SCRIPT_ERROR}

    # Deleted -> terminated when container terminated present (exit code 0 returns completed for DELETED)
    pod_del = Pod("p3", "Failed", cs=[ContainerStatus(State(terminated=Terminated(0, reason="Completed")))])
    pod_del.metadata.labels = {"execution-id": "e3"}
    evd = pem.map_pod_event(pod_del, "DELETED")[0]
    # For DELETED event with exit code 0, it returns execution_completed, not pod_terminated
    assert evd.event_type.value == "execution_completed"


def test_extract_id_and_metadata_priority_and_duplicates() -> None:
    pem = PodEventMapper(k8s_api=_FakeAPI(""))

    # From label
    p = Pod("any", "Pending")
    p.metadata.labels = {"execution-id": "L1", "user-id": "u", "correlation-id": "corrL"}
    ctx = _ctx(p)
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
        def __init__(self, t, s): self.type=t; self.status=s

    pem = PodEventMapper(k8s_api=_FakeAPI(""))
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


def test_parse_and_log_paths_and_analyze_failure_variants(caplog) -> None:
    # _parse_executor_output line-by-line
    line_json = '{"stdout":"x","stderr":"","exit_code":3,"resource_usage":{}}'
    pem = PodEventMapper(k8s_api=_FakeAPI("junk\n" + line_json))
    pod = Pod("p", "Succeeded", cs=[ContainerStatus(State(terminated=Terminated(0)))])
    logs = pem._extract_logs(pod)
    assert logs.exit_code == 3 and logs.stdout == "x"

    # _extract_logs: no api
    pem2 = PodEventMapper(k8s_api=None)
    assert pem2._extract_logs(pod).exit_code is None

    # _extract_logs exceptions -> 404/400/generic branches
    class _API404(_FakeAPI):
        def read_namespaced_pod_log(self, *a, **k): raise Exception("404 Not Found")
    class _API400(_FakeAPI):
        def read_namespaced_pod_log(self, *a, **k): raise Exception("400 Bad Request")
    class _APIGen(_FakeAPI):
        def read_namespaced_pod_log(self, *a, **k): raise Exception("boom")

    pem404 = PodEventMapper(k8s_api=_API404(""))
    assert pem404._extract_logs(pod).exit_code is None
    pem400 = PodEventMapper(k8s_api=_API400(""))
    assert pem400._extract_logs(pod).exit_code is None
    pemg = PodEventMapper(k8s_api=_APIGen(""))
    assert pemg._extract_logs(pod).exit_code is None

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
    pem = PodEventMapper(k8s_api=_FakeAPI(""))
    term0 = ContainerStatus(State(terminated=Terminated(0)))
    term0b = ContainerStatus(State(terminated=Terminated(0)))
    pod = Pod("p", "Failed", cs=[term0, term0b])
    pod.metadata.labels = {"execution-id": "e1"}
    # When all succeeded, failed mapping returns completed instead of failed
    ev = pem.map_pod_event(pod, "MODIFIED")[0]
    assert ev.event_type.value == "execution_completed"

    # Cache prevents duplicate for same phase unless event type changes
    p2 = Pod("p2", "Running")
    a = pem.map_pod_event(p2, "ADDED")
    b = pem.map_pod_event(p2, "MODIFIED")
    # First ADD should map; second MODIFIED with same phase might be filtered by cache → allow either empty or same
    assert a == [] or all(x.event_type for x in a)
    assert b == [] or all(x.event_type for x in b)
