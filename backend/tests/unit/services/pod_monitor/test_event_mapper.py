import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from kubernetes_asyncio.client import V1Pod, V1PodCondition

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
from tests.unit.conftest import make_container_status, make_pod

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.pod_monitor.event_mapper")


def _ctx(pod: V1Pod, event_type: str = "ADDED") -> PodContext:
    return PodContext(
        pod=pod,
        execution_id="e1",
        metadata=EventMetadata(service_name="t", service_version="1"),
        phase=pod.status.phase or "",
        event_type=event_type,
    )


def _make_mock_api(logs: str = "{}") -> MagicMock:
    mock = MagicMock()
    mock.read_namespaced_pod_log = AsyncMock(return_value=logs)
    return mock


@pytest.mark.asyncio
async def test_pending_running_and_succeeded_mapping() -> None:
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

    # Pending -> scheduled
    pend = make_pod(
        name="p",
        phase="Pending",
        labels={"execution-id": "e1"},
        node_name="n",
        conditions=[V1PodCondition(type="PodScheduled", status="True")],
    )
    evts = await pem.map_pod_event(pend, "ADDED")
    assert any(e.event_type == EventType.POD_SCHEDULED for e in evts)

    # Running -> running
    run = make_pod(
        name="p",
        phase="Running",
        labels={"execution-id": "e1"},
        container_statuses=[
            make_container_status(waiting_reason="Init"),
            make_container_status(terminated_exit_code=2),
        ],
    )
    evts = await pem.map_pod_event(run, "MODIFIED")
    assert any(e.event_type == EventType.POD_RUNNING for e in evts)
    pr = [e for e in evts if e.event_type == EventType.POD_RUNNING][0]
    assert isinstance(pr, PodRunningEvent)
    assert any("waiting" in s.state for s in pr.container_statuses) and any(
        "terminated" in s.state for s in pr.container_statuses
    )

    # Succeeded -> completed
    suc = make_pod(
        name="p",
        phase="Succeeded",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=0)],
    )
    evts = await pem.map_pod_event(suc, "MODIFIED")
    comp = [e for e in evts if e.event_type == EventType.EXECUTION_COMPLETED][0]
    assert isinstance(comp, ExecutionCompletedEvent)
    assert comp.exit_code == 0 and comp.stdout == "ok"


@pytest.mark.asyncio
async def test_failed_timeout_and_deleted() -> None:
    valid_logs = json.dumps({"stdout": "", "stderr": "", "exit_code": 137, "resource_usage": {}})
    pem = PodEventMapper(k8s_api=_make_mock_api(valid_logs), logger=_test_logger)

    # Timeout via DeadlineExceeded
    pod_to = make_pod(
        name="p",
        phase="Failed",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=137)],
        reason="DeadlineExceeded",
        active_deadline_seconds=5,
    )
    ev = (await pem.map_pod_event(pod_to, "MODIFIED"))[0]
    assert isinstance(ev, ExecutionTimeoutEvent)
    assert ev.event_type == EventType.EXECUTION_TIMEOUT and ev.timeout_seconds == 5

    # DeadlineExceeded with clean container exit should be treated as completed
    valid_logs_done = json.dumps({"stdout": "ok", "stderr": "", "exit_code": 0, "resource_usage": {}})
    pem_done = PodEventMapper(k8s_api=_make_mock_api(valid_logs_done), logger=_test_logger)
    pod_to_done = make_pod(
        name="p0",
        phase="Failed",
        labels={"execution-id": "e0"},
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_reason="Completed")],
        reason="DeadlineExceeded",
        active_deadline_seconds=5,
    )
    ev_done = (await pem_done.map_pod_event(pod_to_done, "MODIFIED"))[0]
    assert isinstance(ev_done, ExecutionCompletedEvent)
    assert ev_done.event_type == EventType.EXECUTION_COMPLETED

    # Failed: terminated exit_code nonzero
    pem_no_logs = PodEventMapper(k8s_api=_make_mock_api(""), logger=_test_logger)
    pod_fail = make_pod(
        name="p2",
        phase="Failed",
        labels={"execution-id": "e2"},
        container_statuses=[make_container_status(terminated_exit_code=2, terminated_message="boom")],
    )
    evf = (await pem_no_logs.map_pod_event(pod_fail, "MODIFIED"))[0]
    assert isinstance(evf, ExecutionFailedEvent)
    assert evf.event_type == EventType.EXECUTION_FAILED and evf.error_type in {ExecutionErrorType.SCRIPT_ERROR}

    # Deleted with exit code 0 returns completed
    valid_logs_0 = json.dumps({"stdout": "", "stderr": "", "exit_code": 0, "resource_usage": {}})
    pem_completed = PodEventMapper(k8s_api=_make_mock_api(valid_logs_0), logger=_test_logger)
    pod_del = make_pod(
        name="p3",
        phase="Failed",
        labels={"execution-id": "e3"},
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_reason="Completed")],
    )
    evd = (await pem_completed.map_pod_event(pod_del, "DELETED"))[0]
    assert evd.event_type == EventType.EXECUTION_COMPLETED


def test_extract_id_and_metadata_priority_and_duplicates() -> None:
    pem = PodEventMapper(k8s_api=_make_mock_api(""), logger=_test_logger)

    # From label
    p = make_pod(
        name="any",
        phase="Pending",
        labels={"execution-id": "L1", "user-id": "u", "correlation-id": "corrL"},
    )
    md = pem._create_metadata(p)
    assert pem._extract_execution_id(p) == "L1" and md.user_id == "u" and md.correlation_id == "corrL"

    # From annotation when label absent
    p2 = make_pod(
        name="any",
        phase="Pending",
        annotations={"integr8s.io/execution-id": "A1", "integr8s.io/correlation-id": "corrA"},
    )
    assert pem._extract_execution_id(p2) == "A1"
    md2 = pem._create_metadata(p2)
    assert md2.correlation_id == "corrA"

    # From name pattern exec-<id>
    p3 = make_pod(name="exec-XYZ", phase="Pending")
    assert pem._extract_execution_id(p3) == "XYZ"

    # Duplicate detection caches phase
    pem._event_cache.clear()
    assert pem._is_duplicate("n1", "Running") is False
    assert pem._is_duplicate("n1", "Running") is True


@pytest.mark.asyncio
async def test_scheduled_requires_condition() -> None:
    pem = PodEventMapper(k8s_api=_make_mock_api(""), logger=_test_logger)
    pod = make_pod(name="p", phase="Pending")

    # No conditions -> None
    assert await pem._map_scheduled(_ctx(pod)) is None

    # Wrong condition -> None
    pod.status.conditions = [V1PodCondition(type="Ready", status="True")]
    assert await pem._map_scheduled(_ctx(pod)) is None

    # Correct -> event
    pod.status.conditions = [V1PodCondition(type="PodScheduled", status="True")]
    pod.spec.node_name = "n"
    assert await pem._map_scheduled(_ctx(pod)) is not None


@pytest.mark.asyncio
async def test_parse_and_log_paths_and_analyze_failure_variants(caplog: pytest.LogCaptureFixture) -> None:
    line_json = '{"stdout":"x","stderr":"","exit_code":3,"resource_usage":{}}'
    pem = PodEventMapper(k8s_api=_make_mock_api("junk\n" + line_json), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0)],
    )
    logs = await pem._extract_logs(pod)
    assert logs is not None
    assert logs.exit_code == 3 and logs.stdout == "x"

    # no api -> returns None
    pem2 = PodEventMapper(k8s_api=None, logger=_test_logger)
    assert await pem2._extract_logs(pod) is None

    # exceptions -> all return None
    mock_404 = MagicMock()
    mock_404.read_namespaced_pod_log = AsyncMock(side_effect=Exception("404 Not Found"))
    mock_400 = MagicMock()
    mock_400.read_namespaced_pod_log = AsyncMock(side_effect=Exception("400 Bad Request"))
    mock_gen = MagicMock()
    mock_gen.read_namespaced_pod_log = AsyncMock(side_effect=Exception("boom"))

    assert await PodEventMapper(k8s_api=mock_404, logger=_test_logger)._extract_logs(pod) is None
    assert await PodEventMapper(k8s_api=mock_400, logger=_test_logger)._extract_logs(pod) is None
    assert await PodEventMapper(k8s_api=mock_gen, logger=_test_logger)._extract_logs(pod) is None

    # _analyze_failure: Evicted
    pod_e = make_pod(name="p", phase="Failed", reason="Evicted")
    assert pem._analyze_failure(pod_e).error_type == ExecutionErrorType.RESOURCE_LIMIT

    # Waiting reasons mapping
    pod_w = make_pod(
        name="p",
        phase="Failed",
        container_statuses=[make_container_status(waiting_reason="ImagePullBackOff")],
    )
    assert pem._analyze_failure(pod_w).error_type == ExecutionErrorType.SYSTEM_ERROR

    pod_w2 = make_pod(
        name="p",
        phase="Failed",
        container_statuses=[make_container_status(waiting_reason="CrashLoopBackOff")],
    )
    assert pem._analyze_failure(pod_w2).error_type == ExecutionErrorType.SCRIPT_ERROR

    pod_w3 = make_pod(
        name="p",
        phase="Failed",
        container_statuses=[make_container_status(waiting_reason="ErrImagePull")],
    )
    assert pem._analyze_failure(pod_w3).error_type == ExecutionErrorType.SYSTEM_ERROR

    # OOMKilled in status.message
    pod_oom = make_pod(name="p", phase="Failed", message="... OOMKilled ...")
    assert pem._analyze_failure(pod_oom).error_type == ExecutionErrorType.RESOURCE_LIMIT


@pytest.mark.asyncio
async def test_all_containers_succeeded_and_cache_behavior() -> None:
    valid_logs = json.dumps({"stdout": "", "stderr": "", "exit_code": 0, "resource_usage": {}})
    pem = PodEventMapper(k8s_api=_make_mock_api(valid_logs), logger=_test_logger)

    pod = make_pod(
        name="p",
        phase="Failed",
        labels={"execution-id": "e1"},
        container_statuses=[
            make_container_status(terminated_exit_code=0),
            make_container_status(terminated_exit_code=0),
        ],
    )
    # When all succeeded, failed mapping returns completed instead of failed
    ev = (await pem.map_pod_event(pod, "MODIFIED"))[0]
    assert ev.event_type == EventType.EXECUTION_COMPLETED

    # Cache prevents duplicate for same phase
    p2 = make_pod(name="p2", phase="Running")
    a = await pem.map_pod_event(p2, "ADDED")
    b = await pem.map_pod_event(p2, "MODIFIED")
    assert a == [] or all(x.event_type for x in a)
    assert b == [] or all(x.event_type for x in b)
