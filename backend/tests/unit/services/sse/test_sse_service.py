import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import datetime, timezone
from typing import Any

import pytest
import structlog

from app.db.docs import ExecutionDocument
from app.domain.enums import (
    EventType,
    ExecutionStatus,
    NotificationSeverity,
    NotificationStatus,
    ReplayStatus,
    UserRole,
)
from app.domain.execution.models import ExecutionResultDomain
from app.domain.sse import DomainNotificationSSEPayload, DomainReplaySSEPayload, SSEExecutionEventData
from app.services.sse import SSEService

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.sse.sse_service")

_NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


class _FakeBus:
    """Fake SSERedisBus backed by asyncio queues."""

    def __init__(self) -> None:
        self._exec_q: asyncio.Queue[SSEExecutionEventData | None] = asyncio.Queue()
        self._notif_q: asyncio.Queue[DomainNotificationSSEPayload | None] = asyncio.Queue()
        self._replay_q: asyncio.Queue[DomainReplaySSEPayload | None] = asyncio.Queue()
        self.exec_closed = False
        self.notif_closed = False
        self.replay_closed = False

    async def push_exec(self, event: SSEExecutionEventData | None) -> None:
        await self._exec_q.put(event)

    async def push_notif(self, payload: DomainNotificationSSEPayload | None) -> None:
        await self._notif_q.put(payload)

    async def push_replay(self, status: DomainReplaySSEPayload | None) -> None:
        await self._replay_q.put(status)

    async def listen_execution(self, execution_id: str) -> AsyncGenerator[SSEExecutionEventData, None]:
        try:
            while True:
                item = await self._exec_q.get()
                if item is None:
                    return
                yield item
        finally:
            self.exec_closed = True

    async def listen_notifications(self, user_id: str) -> AsyncGenerator[DomainNotificationSSEPayload, None]:
        try:
            while True:
                item = await self._notif_q.get()
                if item is None:
                    return
                yield item
        finally:
            self.notif_closed = True

    async def listen_replay(self, session_id: str) -> AsyncGenerator[DomainReplaySSEPayload, None]:
        try:
            while True:
                item = await self._replay_q.get()
                if item is None:
                    return
                yield item
        finally:
            self.replay_closed = True


class _FakeExecRepo:
    """Fake ExecutionRepository with configurable return values."""

    def __init__(
        self,
        execution: ExecutionDocument | None = None,
        result: ExecutionResultDomain | None = None,
    ) -> None:
        self._execution = execution
        self._result = result

    async def get_execution(self, execution_id: str) -> ExecutionDocument | None:
        return self._execution

    async def get_terminal_result(self, execution_id: str) -> ExecutionResultDomain | None:
        return self._result


def _decode(evt: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(evt["data"])
    return result


def _make_service(bus: _FakeBus, exec_repo: _FakeExecRepo | None = None) -> SSEService:
    return SSEService(
        bus=bus,  # type: ignore[arg-type]
        execution_repository=exec_repo or _FakeExecRepo(),  # type: ignore[arg-type]
        logger=_test_logger,
    )


async def test_execution_stream_prepends_status_from_db() -> None:
    execution = ExecutionDocument(script="x", execution_id="exec-1", status=ExecutionStatus.RUNNING)
    bus = _FakeBus()
    svc = _make_service(bus, _FakeExecRepo(execution=execution))

    agen = await svc.create_execution_stream("exec-1", user_id="u1", user_role=UserRole.USER)

    # Signal end of live stream so the generator can finish
    await bus.push_exec(None)

    # First item must be the STATUS prepended from DB
    stat = await agen.__anext__()
    data = _decode(stat)
    assert data["event_type"] == "status"
    assert data["execution_id"] == "exec-1"

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_execution_stream_closes_on_terminal_event() -> None:
    bus = _FakeBus()
    svc = _make_service(
        bus,
        _FakeExecRepo(execution=ExecutionDocument(script="x", execution_id="exec-1", status=ExecutionStatus.RUNNING)),
    )

    agen = await svc.create_execution_stream("exec-1", user_id="u1", user_role=UserRole.USER)

    # DB status prepend is always yielded first
    stat = await agen.__anext__()
    assert _decode(stat)["event_type"] == "status"

    await bus.push_exec(
        SSEExecutionEventData(
            event_type=EventType.EXECUTION_FAILED,
            execution_id="exec-1",
        )
    )
    failed = await agen.__anext__()
    assert _decode(failed)["event_type"] == EventType.EXECUTION_FAILED

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_execution_stream_enriches_result_stored() -> None:
    result = ExecutionResultDomain(
        execution_id="exec-2",
        status=ExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="out",
        stderr="",
    )
    bus = _FakeBus()
    svc = _make_service(
        bus,
        _FakeExecRepo(
            execution=ExecutionDocument(script="x", execution_id="exec-2", status=ExecutionStatus.RUNNING),
            result=result,
        ),
    )

    agen = await svc.create_execution_stream("exec-2", user_id="u1", user_role=UserRole.USER)

    # Consume DB status prepend
    await agen.__anext__()

    await bus.push_exec(
        SSEExecutionEventData(
            event_type=EventType.RESULT_STORED,
            execution_id="exec-2",
        )
    )
    evt = await agen.__anext__()
    data = _decode(evt)
    assert data["event_type"] == EventType.RESULT_STORED
    assert data["result"] is not None
    assert data["result"]["execution_id"] == "exec-2"

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_execution_stream_for_finished_execution_sends_result_and_closes() -> None:
    result = ExecutionResultDomain(
        execution_id="exec-3", status=ExecutionStatus.COMPLETED, exit_code=0, stdout="done", stderr=""
    )
    execution = ExecutionDocument(script="x", execution_id="exec-3", status=ExecutionStatus.COMPLETED)
    bus = _FakeBus()
    svc = _make_service(bus, _FakeExecRepo(execution=execution, result=result))

    agen = await svc.create_execution_stream("exec-3", user_id="u1", user_role=UserRole.USER)

    assert _decode(await agen.__anext__())["status"] == ExecutionStatus.COMPLETED
    stored = _decode(await agen.__anext__())
    assert stored["event_type"] == EventType.RESULT_STORED
    assert stored["result"]["stdout"] == "done"
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_notification_stream_yields_notification_and_cleans_up() -> None:
    """Notification stream yields {"event": "notification", "data": ...} for each message."""
    bus = _FakeBus()
    svc = _make_service(bus)

    async with aclosing(svc.create_notification_stream(user_id="u1")) as agen:
        await bus.push_notif(
            DomainNotificationSSEPayload(
                notification_id="n1",
                severity=NotificationSeverity.LOW,
                status=NotificationStatus.PENDING,
                tags=[],
                subject="s",
                body="b",
                action_url="",
                created_at=_NOW,
            )
        )

        notif = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
        assert notif["event"] == "notification"
        data = json.loads(notif["data"])
        assert data["notification_id"] == "n1"
        assert data["subject"] == "s"
    assert bus.notif_closed


async def test_replay_stream_yields_initial_then_live() -> None:
    """Replay pipeline yields initial status from DB then streams live updates."""
    bus = _FakeBus()
    svc = _make_service(bus)

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

    assert await agen.__anext__() is initial

    # Push a live update
    await bus.push_replay(
        DomainReplaySSEPayload(
            session_id="sess-1",
            status=ReplayStatus.RUNNING,
            total_events=5,
            replayed_events=3,
            failed_events=0,
            skipped_events=0,
            replay_id="replay-1",
            created_at=_NOW,
        )
    )

    second = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert second.replayed_events == 3

    # Push terminal status
    await bus.push_replay(
        DomainReplaySSEPayload(
            session_id="sess-1",
            status=ReplayStatus.COMPLETED,
            total_events=5,
            replayed_events=5,
            failed_events=0,
            skipped_events=0,
            replay_id="replay-1",
            created_at=_NOW,
        )
    )

    third = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert third.status == ReplayStatus.COMPLETED

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_replay_stream_terminal_initial_closes_immediately() -> None:
    """If the initial replay status is terminal, the stream closes after yielding it."""
    bus = _FakeBus()
    svc = _make_service(bus)

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

    assert await agen.__anext__() is initial

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()
