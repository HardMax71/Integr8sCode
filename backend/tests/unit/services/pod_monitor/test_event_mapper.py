from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
import structlog
from kubernetes_asyncio.client import V1Pod, V1PodCondition
from kubernetes_asyncio.client.rest import ApiException

from app.domain.enums import EventType, ExecutionErrorType
from app.domain.events import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    PodRunningEvent,
)
from app.services.pod_monitor import PodContext, PodEventMapper, WatchEventType
from tests.unit.conftest import make_container_status, make_pod, make_pod_log_response

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.pod_monitor.event_mapper")

_TERM_MSG = "exit_code=0\ncpu_jiffies=100\nclk_tck=100\npeak_memory_kb=1024\nwall_seconds=0.5\n"
_TERM_MSG_EMPTY = "exit_code=0\ncpu_jiffies=0\nclk_tck=100\npeak_memory_kb=0\nwall_seconds=0\n"
_UNREADABLE = "The output couldn't be read from the pod's log."


def _framed(stdout: str | bytes = "", stderr: str | bytes = "") -> bytes:
    """Frame output the way entrypoint.sh does: each length counts the stream's bytes."""
    out = stdout.encode() if isinstance(stdout, str) else stdout
    err = stderr.encode() if isinstance(stderr, str) else stderr
    return b"STDOUT %d\n%bSTDERR %d\n%b" % (len(out), out, len(err), err)


def _ctx(pod: V1Pod, event_type: WatchEventType = WatchEventType.ADDED) -> PodContext:
    return PodContext(
        pod=pod,
        execution_id="e1",
        metadata=EventMetadata(service_name="t", service_version="1", user_id="u1"),
        phase=pod.status.phase or "",
        event_type=event_type,
    )


def _make_mock_api(logs: bytes = b"") -> MagicMock:
    mock = MagicMock()
    mock.read_namespaced_pod_log = AsyncMock(return_value=make_pod_log_response(logs))
    return mock


async def test_pending_running_and_succeeded_mapping() -> None:
    logs = _framed("ok", "")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)

    # Pending -> scheduled
    pend = make_pod(
        name="p",
        phase="Pending",
        labels={"execution-id": "e1"},
        node_name="n",
        conditions=[V1PodCondition(type="PodScheduled", status="True")],
    )
    evts = await pem.map_pod_event(pend, WatchEventType.ADDED)
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
    evts = await pem.map_pod_event(run, WatchEventType.MODIFIED)
    assert any(e.event_type == EventType.POD_RUNNING for e in evts)
    pr = [e for e in evts if e.event_type == EventType.POD_RUNNING][0]
    assert isinstance(pr, PodRunningEvent)
    assert any("waiting" in s.state for s in pr.container_statuses) and any(
        "terminated" in s.state for s in pr.container_statuses
    )

    # Succeeded -> completed (with termination message for resource metrics)
    suc = make_pod(
        name="p",
        phase="Succeeded",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    evts = await pem.map_pod_event(suc, WatchEventType.MODIFIED)
    comp = [e for e in evts if e.event_type == EventType.EXECUTION_COMPLETED][0]
    assert isinstance(comp, ExecutionCompletedEvent)
    assert comp.exit_code == 0 and comp.stdout == "ok"
    assert comp.resource_usage is not None
    assert comp.resource_usage.cpu_time_jiffies == 100
    assert comp.resource_usage.peak_memory_kb == 1024


async def test_failed_timeout_and_deleted() -> None:
    logs = _framed("", "")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)

    # Timeout via DeadlineExceeded (entrypoint killed, no termination message)
    pod_to = make_pod(
        name="p",
        phase="Failed",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=137)],
        reason="DeadlineExceeded",
        active_deadline_seconds=5,
    )
    ev = (await pem.map_pod_event(pod_to, WatchEventType.MODIFIED))[0]
    assert isinstance(ev, ExecutionTimeoutEvent)
    assert ev.event_type == EventType.EXECUTION_TIMEOUT and ev.timeout_seconds == 5

    # DeadlineExceeded with clean container exit should be treated as completed
    logs_done = _framed("ok", "")
    pem_done = PodEventMapper(k8s_api=_make_mock_api(logs_done), logger=_test_logger)
    pod_to_done = make_pod(
        name="p0",
        phase="Failed",
        labels={"execution-id": "e0"},
        container_statuses=[
            make_container_status(terminated_exit_code=0, terminated_reason="Completed", terminated_message=_TERM_MSG)
        ],
        reason="DeadlineExceeded",
        active_deadline_seconds=5,
    )
    ev_done = (await pem_done.map_pod_event(pod_to_done, WatchEventType.MODIFIED))[0]
    assert isinstance(ev_done, ExecutionCompletedEvent)
    assert ev_done.event_type == EventType.EXECUTION_COMPLETED

    # Failed: terminated exit_code nonzero
    pem_no_logs = PodEventMapper(k8s_api=_make_mock_api(), logger=_test_logger)
    pod_fail = make_pod(
        name="p2",
        phase="Failed",
        labels={"execution-id": "e2"},
        container_statuses=[make_container_status(terminated_exit_code=2, terminated_message="boom")],
    )
    evf = (await pem_no_logs.map_pod_event(pod_fail, WatchEventType.MODIFIED))[0]
    assert isinstance(evf, ExecutionFailedEvent)
    assert evf.event_type == EventType.EXECUTION_FAILED and evf.error_type in {ExecutionErrorType.SCRIPT_ERROR}

    # Deleted with exit code 0 returns completed
    logs_0 = _framed("", "")
    pem_completed = PodEventMapper(k8s_api=_make_mock_api(logs_0), logger=_test_logger)
    pod_del = make_pod(
        name="p3",
        phase="Failed",
        labels={"execution-id": "e3"},
        container_statuses=[
            make_container_status(
                terminated_exit_code=0, terminated_reason="Completed", terminated_message=_TERM_MSG_EMPTY
            )
        ],
    )
    evd = (await pem_completed.map_pod_event(pod_del, WatchEventType.DELETED))[0]
    assert evd.event_type == EventType.EXECUTION_COMPLETED


def test_extract_id_and_metadata_priority_and_duplicates() -> None:
    pem = PodEventMapper(k8s_api=_make_mock_api(), logger=_test_logger)

    # From label
    p = make_pod(
        name="any",
        phase="Pending",
        labels={"execution-id": "L1", "user-id": "u"},
    )
    md = pem._create_metadata(p)
    assert pem._extract_execution_id(p) == "L1" and md.user_id == "u"

    # From annotation when label absent
    p2 = make_pod(
        name="any",
        phase="Pending",
        annotations={"integr8s.io/execution-id": "A1"},
    )
    assert pem._extract_execution_id(p2) == "A1"

    # From name pattern exec-<id>
    p3 = make_pod(name="exec-XYZ", phase="Pending")
    assert pem._extract_execution_id(p3) == "XYZ"


async def test_scheduled_requires_condition() -> None:
    pem = PodEventMapper(k8s_api=_make_mock_api(), logger=_test_logger)
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


async def test_extract_logs_with_framed_output() -> None:
    """Test log extraction with length-prefixed framing and termination message."""
    logs = _framed("hello world", "some warning")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    result = await pem._extract_logs(pod)
    assert result is not None
    assert result.stdout == "hello world"
    assert result.stderr == "some warning"
    assert result.exit_code == 0
    assert result.resource_usage.cpu_time_jiffies == 100
    assert result.resource_usage.clk_tck_hertz == 100
    assert result.resource_usage.peak_memory_kb == 1024
    assert result.resource_usage.execution_time_wall_seconds == 0.5


async def test_extract_logs_reads_from_the_start_as_bytes() -> None:
    """The STDOUT header is at the start, so a capped read from the start always keeps it."""
    api = _make_mock_api(_framed("ok", ""))
    pem = PodEventMapper(k8s_api=api, logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    await pem._extract_logs(pod)

    kwargs = api.read_namespaced_pod_log.call_args.kwargs
    assert kwargs["limit_bytes"] == PodEventMapper._MAX_LOG_BYTES
    assert kwargs["_preload_content"] is False
    assert "tail_lines" not in kwargs


async def test_extract_logs_utf8_output() -> None:
    """Non-ASCII output used to overrun the char-sliced STDOUT frame and lose both streams."""
    pem = PodEventMapper(k8s_api=_make_mock_api(_framed("héllo ✓\n", "🚀 done\n")), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    result = await pem._extract_logs(pod)
    assert result is not None
    assert result.stdout == "héllo ✓\n"
    assert result.stderr == "🚀 done\n"


async def test_extract_logs_empty_stdout_stderr() -> None:
    """Test extraction when both stdout and stderr are empty."""
    logs = _framed("", "")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG_EMPTY)],
    )
    result = await pem._extract_logs(pod)
    assert result is not None
    assert result.stdout == ""
    assert result.stderr == ""


async def test_extract_logs_large_stdout() -> None:
    """Test extraction with large stdout content."""
    large_content = "x" * 50_000
    logs = _framed(large_content, "err")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    result = await pem._extract_logs(pod)
    assert result is not None
    assert result.stdout == large_content
    assert result.stderr == "err"


async def test_extract_logs_missing_termination_message() -> None:
    """Test extraction when termination message is absent — defaults to zero values."""
    logs = _framed("out", "")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0)],
    )
    result = await pem._extract_logs(pod)
    assert result is not None
    assert result.stdout == "out"
    assert result.resource_usage.cpu_time_jiffies == 0
    assert result.resource_usage.clk_tck_hertz == 100
    assert result.resource_usage.peak_memory_kb == 0


async def test_extract_logs_malformed_framing_returns_empty() -> None:
    """Test that malformed log framing returns empty strings."""
    pem = PodEventMapper(k8s_api=_make_mock_api(b"garbage data"), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    result = await pem._extract_logs(pod)
    assert result is not None
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "error",
    [ApiException(status=500, reason="boom"), aiohttp.ClientConnectionError("boom"), TimeoutError("boom")],
)
async def test_unreadable_log_leaves_a_note_and_keeps_the_result(error: Exception) -> None:
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    mock_err = MagicMock()
    mock_err.read_namespaced_pod_log = AsyncMock(side_effect=error)

    logs = await PodEventMapper(k8s_api=mock_err, logger=_test_logger)._extract_logs(pod)

    assert logs is not None
    assert (logs.stdout, logs.stderr, logs.exit_code) == ("", _UNREADABLE, 0)
    assert logs.resource_usage.cpu_time_jiffies == 100


async def test_an_http_error_status_counts_as_unreadable() -> None:
    """A raw response does not raise on its own, so an error status must still be caught."""
    pod = make_pod(
        name="p",
        phase="Succeeded",
        container_statuses=[make_container_status(terminated_exit_code=0)],
    )
    api = _make_mock_api()
    api.read_namespaced_pod_log.return_value.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=404
    )

    logs = await PodEventMapper(k8s_api=api, logger=_test_logger)._extract_logs(pod)

    assert logs is not None and logs.stderr == _UNREADABLE


def _failing_log_api() -> MagicMock:
    api = MagicMock()
    api.read_namespaced_pod_log = AsyncMock(side_effect=ApiException(status=403, reason="Forbidden"))
    return api


async def test_succeeded_pod_with_unreadable_log_still_completes_once() -> None:
    pem = PodEventMapper(k8s_api=_failing_log_api(), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )

    [event] = await pem.map_pod_event(pod, WatchEventType.MODIFIED)

    assert isinstance(event, ExecutionCompletedEvent)
    assert (event.exit_code, event.stdout, event.stderr) == (0, "", _UNREADABLE)
    assert await pem.map_pod_event(pod, WatchEventType.MODIFIED) == []


async def test_timed_out_pod_with_unreadable_log_is_a_timeout() -> None:
    pem = PodEventMapper(k8s_api=_failing_log_api(), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Failed",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=137)],
        reason="DeadlineExceeded",
        active_deadline_seconds=5,
    )

    [event] = await pem.map_pod_event(pod, WatchEventType.MODIFIED)

    assert isinstance(event, ExecutionTimeoutEvent)
    assert (event.timeout_seconds, event.stderr) == (5, _UNREADABLE)


async def test_a_phase_without_an_event_is_tried_again() -> None:
    """The first Pending event often comes before the scheduler placed the pod."""
    pem = PodEventMapper(k8s_api=_make_mock_api(), logger=_test_logger)
    unplaced = make_pod(name="p", phase="Pending", labels={"execution-id": "e1"})
    placed = make_pod(
        name="p",
        phase="Pending",
        labels={"execution-id": "e1"},
        node_name="n",
        conditions=[V1PodCondition(type="PodScheduled", status="True")],
    )

    assert await pem.map_pod_event(unplaced, WatchEventType.ADDED) == []
    assert [e.event_type for e in await pem.map_pod_event(placed, WatchEventType.MODIFIED)] == [EventType.POD_SCHEDULED]
    assert await pem.map_pod_event(placed, WatchEventType.MODIFIED) == []


async def test_deleting_a_finished_pod_sends_pod_terminated_and_forgets_it() -> None:
    pem = PodEventMapper(k8s_api=_make_mock_api(_framed("ok", "")), logger=_test_logger)
    pod = make_pod(
        name="p",
        phase="Succeeded",
        labels={"execution-id": "e1"},
        container_statuses=[make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG)],
    )
    await pem.map_pod_event(pod, WatchEventType.MODIFIED)

    deleted = await pem.map_pod_event(pod, WatchEventType.DELETED)

    assert [e.event_type for e in deleted] == [EventType.POD_TERMINATED]
    assert "p" not in pem._event_cache


def test_analyze_failure_variants() -> None:
    """Test _analyze_failure with various pod failure scenarios."""
    pem = PodEventMapper(k8s_api=_make_mock_api(), logger=_test_logger)

    # Evicted
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


async def test_all_containers_succeeded_and_cache_behavior() -> None:
    logs = _framed("", "")
    pem = PodEventMapper(k8s_api=_make_mock_api(logs), logger=_test_logger)

    pod = make_pod(
        name="p",
        phase="Failed",
        labels={"execution-id": "e1"},
        container_statuses=[
            make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG_EMPTY),
            make_container_status(terminated_exit_code=0, terminated_message=_TERM_MSG_EMPTY),
        ],
    )
    # When all succeeded, failed mapping returns completed instead of failed
    ev = (await pem.map_pod_event(pod, WatchEventType.MODIFIED))[0]
    assert ev.event_type == EventType.EXECUTION_COMPLETED

    # Cache prevents duplicate for same phase
    p2 = make_pod(name="p2", phase="Running", labels={"execution-id": "e2"})
    a = await pem.map_pod_event(p2, WatchEventType.ADDED)
    b = await pem.map_pod_event(p2, WatchEventType.MODIFIED)
    assert [e.event_type for e in a] == [EventType.POD_RUNNING]
    assert b == []


def test_parse_termination_message() -> None:
    """Test _parse_termination_message with various inputs."""
    parse = PodEventMapper._parse_termination_message

    # Normal message
    result = parse("exit_code=0\ncpu_jiffies=100\nclk_tck=100\npeak_memory_kb=1024\nwall_seconds=0.5\n")
    assert result == {
        "exit_code": "0",
        "cpu_jiffies": "100",
        "clk_tck": "100",
        "peak_memory_kb": "1024",
        "wall_seconds": "0.5",
    }

    # Empty string
    assert parse("") == {}

    # Lines without = are skipped
    assert parse("no-equals\ncpu_jiffies=50\n") == {"cpu_jiffies": "50"}

    # Value containing = sign
    assert parse("key=val=ue\n") == {"key": "val=ue"}


def test_parse_framed_output() -> None:
    """Test _parse_framed_output with various inputs."""
    parse = PodEventMapper._parse_framed_output

    # Normal case
    assert parse(b"STDOUT 5\nhelloSTDERR 3\nerr") == ("hello", "err")

    # Empty both
    assert parse(b"STDOUT 0\nSTDERR 0\n") == ("", "")

    # Content with newlines
    assert parse(_framed("line1\nline2\nline3", "")) == ("line1\nline2\nline3", "")

    # Malformed input
    assert parse(b"garbage") == ("", "")
    assert parse(b"") == ("", "")

    # Content containing STDOUT/STDERR markers (length-prefix makes this safe)
    tricky = "STDOUT 5\nfake"
    assert parse(_framed(tricky, "")) == (tricky, "")


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("héllo ✓\n", "🚀\n"),
        ("日本語のテキスト", ""),
        ("", "Ошибка: STDERR 3\n"),
        ("mixed ascii and ünïcödé\nsecond line ✓\n", "warn ⚠\n"),
    ],
)
def test_parse_framed_output_utf8_roundtrip(stdout: str, stderr: str) -> None:
    assert PodEventMapper._parse_framed_output(_framed(stdout, stderr)) == (stdout, stderr)


def test_parse_framed_output_keeps_truncated_stream() -> None:
    """entrypoint.sh cuts a long stream at a byte count, which can split a character before its notice."""
    kept = "a" * 10 + "é"
    cut = kept.encode()[:-1]
    notice = b"\n[stdout truncated: showing the first 11 bytes]\n"
    stdout, stderr = PodEventMapper._parse_framed_output(_framed(cut + notice, "🚀"))
    assert stdout == "a" * 10 + "\ufffd" + notice.decode()
    assert stderr == "🚀"
