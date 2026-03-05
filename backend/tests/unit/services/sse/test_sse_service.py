import asyncio
import json
import structlog
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.metrics import ConnectionMetrics
from app.domain.enums import EventType, ExecutionStatus, NotificationSeverity, NotificationStatus, ReplayStatus, SSEControlEvent, UserRole
from app.domain.execution.models import DomainExecution, ExecutionResultDomain
from app.domain.sse import DomainNotificationSSEPayload, DomainReplaySSEPayload, SSEExecutionEventData
from app.services.sse import SSEService
from app.services.sse.sse_service import _exec_adapter, _notif_adapter

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.sse.sse_service")

_NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


class _FakeRedis:
    """Fake Redis with Streams support (XADD / XREAD / EXPIRE)."""

    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, dict[bytes, bytes]]]] = {}
        self._counter = 0

    async def xadd(self, key: str, fields: dict[str, bytes], **_kw: Any) -> str:
        self._counter += 1
        msg_id = f"{self._counter}-0"
        encoded = {k.encode() if isinstance(k, str) else k: v for k, v in fields.items()}
        self._streams.setdefault(key, []).append((msg_id, encoded))
        return msg_id

    async def xread(self, streams: dict[str, str], **_kw: Any) -> list[tuple[str, list[tuple[str, dict[bytes, bytes]]]]] | None:
        result: list[tuple[str, list[tuple[str, dict[bytes, bytes]]]]] = []
        for key, after in streams.items():
            after_seq = int(after.split("-")[0])
            msgs = [(mid, f) for mid, f in self._streams.get(key, []) if int(mid.split("-")[0]) > after_seq]
            if msgs:
                result.append((key, msgs))
        return result or None

    async def expire(self, key: str, seconds: int) -> bool:  # noqa: ARG002
        return True


class _FakeExecRepo:
    """Fake ExecutionRepository with configurable return values."""

    def __init__(
        self,
        execution: DomainExecution | None = None,
        result: ExecutionResultDomain | None = None,
    ) -> None:
        self._execution = execution
        self._result = result

    async def get_execution(self, execution_id: str) -> DomainExecution | None:  # noqa: ARG002
        return self._execution

    async def get_execution_result(self, execution_id: str) -> ExecutionResultDomain | None:  # noqa: ARG002
        return self._result


def _decode(evt: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(evt["data"])
    return result


def _make_service(fake_redis: _FakeRedis, exec_repo: _FakeExecRepo = _FakeExecRepo()) -> SSEService:
    return SSEService(
        redis_client=fake_redis,  # type: ignore[arg-type]
        execution_repository=exec_repo,  # type: ignore[arg-type]
        logger=_test_logger,
        connection_metrics=MagicMock(spec=ConnectionMetrics),
        poll_interval=0.01,
    )


@pytest.mark.asyncio
async def test_execution_stream_prepends_status_from_db() -> None:
    execution = DomainExecution(execution_id="exec-1", status=ExecutionStatus.RUNNING)
    fake_redis = _FakeRedis()
    svc = _make_service(fake_redis, _FakeExecRepo(execution=execution))

    agen = await svc.create_execution_stream("exec-1", user_id="u1", user_role=UserRole.USER)

    # First item must be the STATUS prepended from DB
    stat = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    data = _decode(stat)
    assert data["event_type"] == "status"
    assert data["execution_id"] == "exec-1"


@pytest.mark.asyncio
async def test_execution_stream_closes_on_terminal_event() -> None:
    fake_redis = _FakeRedis()
    svc = _make_service(fake_redis, _FakeExecRepo(execution=DomainExecution(execution_id="exec-1", status=ExecutionStatus.RUNNING)))

    agen = await svc.create_execution_stream("exec-1", user_id="u1", user_role=UserRole.USER)

    # DB status prepend is always yielded first
    stat = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert _decode(stat)["event_type"] == "status"

    # Push a terminal event into the stream
    await fake_redis.xadd("sse:exec:exec-1", {"d": _exec_adapter.dump_json(SSEExecutionEventData(
        event_type=EventType.EXECUTION_FAILED,
        execution_id="exec-1",
    ))})

    failed = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert _decode(failed)["event_type"] == EventType.EXECUTION_FAILED

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), timeout=2.0)


@pytest.mark.asyncio
async def test_execution_stream_enriches_result_stored() -> None:
    result = ExecutionResultDomain(
        execution_id="exec-2",
        status=ExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="out",
        stderr="",
    )
    fake_redis = _FakeRedis()
    svc = _make_service(fake_redis, _FakeExecRepo(execution=DomainExecution(execution_id="exec-2", status=ExecutionStatus.RUNNING), result=result))

    agen = await svc.create_execution_stream("exec-2", user_id="u1", user_role=UserRole.USER)

    # Consume DB status prepend
    await asyncio.wait_for(agen.__anext__(), timeout=2.0)

    await fake_redis.xadd("sse:exec:exec-2", {"d": _exec_adapter.dump_json(SSEExecutionEventData(
        event_type=EventType.RESULT_STORED,
        execution_id="exec-2",
    ))})

    evt = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    data = _decode(evt)
    assert data["event_type"] == EventType.RESULT_STORED
    assert data["result"] is not None
    assert data["result"]["execution_id"] == "exec-2"

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), timeout=2.0)


@pytest.mark.asyncio
async def test_notification_stream_yields_notification() -> None:
    """Notification stream yields {"event": "notification", "data": ...} for each message."""
    fake_redis = _FakeRedis()
    svc = _make_service(fake_redis)

    # Push notification into stream before starting the generator
    await fake_redis.xadd("sse:notif:u1", {"d": _notif_adapter.dump_json(DomainNotificationSSEPayload(
        notification_id="n1",
        severity=NotificationSeverity.LOW,
        status=NotificationStatus.PENDING,
        tags=[],
        subject="s",
        body="b",
        action_url="",
        created_at=_NOW,
    ))})

    agen = svc.create_notification_stream(user_id="u1")

    notif = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert notif["event"] == "notification"
    data = json.loads(notif["data"])
    assert data["notification_id"] == "n1"
    assert data["subject"] == "s"
    assert data["channel"] == "in_app"


@pytest.mark.asyncio
async def test_replay_stream_yields_initial_then_live() -> None:
    """Replay pipeline yields initial status from DB then streams live updates."""
    fake_redis = _FakeRedis()
    svc = _make_service(fake_redis)

    initial = DomainReplaySSEPayload(
        session_id="sess-1",
        status=ReplayStatus.RUNNING,
        total_events=5,
        replayed_events=0,
        failed_events=0,
        skipped_events=0,
        replay_id="replay-1",
        created_at=_NOW,
    )

    agen = await svc.create_replay_stream(initial)

    # First item is the initial status
    first = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    data = _decode(first)
    assert data["session_id"] == "sess-1"
    assert data["status"] == "running"
    assert data["replayed_events"] == 0

    # Push a live update into the stream
    from app.services.sse.sse_service import _replay_adapter
    await fake_redis.xadd("sse:replay:sess-1", {"d": _replay_adapter.dump_json(DomainReplaySSEPayload(
        session_id="sess-1",
        status=ReplayStatus.RUNNING,
        total_events=5,
        replayed_events=3,
        failed_events=0,
        skipped_events=0,
        replay_id="replay-1",
        created_at=_NOW,
    ))})

    second = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    data2 = _decode(second)
    assert data2["replayed_events"] == 3

    # Push terminal status
    await fake_redis.xadd("sse:replay:sess-1", {"d": _replay_adapter.dump_json(DomainReplaySSEPayload(
        session_id="sess-1",
        status=ReplayStatus.COMPLETED,
        total_events=5,
        replayed_events=5,
        failed_events=0,
        skipped_events=0,
        replay_id="replay-1",
        created_at=_NOW,
    ))})

    third = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    data3 = _decode(third)
    assert data3["status"] == "completed"

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), timeout=2.0)


@pytest.mark.asyncio
async def test_replay_stream_terminal_initial_closes_immediately() -> None:
    """If the initial replay status is terminal, the stream closes after yielding it."""
    fake_redis = _FakeRedis()
    svc = _make_service(fake_redis)

    initial = DomainReplaySSEPayload(
        session_id="sess-2",
        status=ReplayStatus.COMPLETED,
        total_events=3,
        replayed_events=3,
        failed_events=0,
        skipped_events=0,
        replay_id="replay-2",
        created_at=_NOW,
    )

    agen = await svc.create_replay_stream(initial)

    first = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    data = _decode(first)
    assert data["status"] == "completed"

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), timeout=2.0)
