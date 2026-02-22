import asyncio
import json
import structlog
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest

from app.domain.enums import EventType, ExecutionStatus, NotificationSeverity, NotificationStatus, SSEControlEvent, UserRole
from app.domain.execution.models import DomainExecution, ExecutionResultDomain
from app.domain.sse import DomainNotificationSSEPayload, SSEExecutionEventData
from app.services.sse import SSEService

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.sse.sse_service")

_NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


class _FakeBus:
    """Fake SSERedisBus backed by asyncio queues."""

    def __init__(self) -> None:
        self._exec_q: asyncio.Queue[SSEExecutionEventData | None] = asyncio.Queue()
        self._notif_q: asyncio.Queue[DomainNotificationSSEPayload | None] = asyncio.Queue()
        self.exec_closed = False
        self.notif_closed = False

    async def push_exec(self, event: SSEExecutionEventData | None) -> None:
        await self._exec_q.put(event)

    async def push_notif(self, payload: DomainNotificationSSEPayload | None) -> None:
        await self._notif_q.put(payload)

    async def listen_execution(self, execution_id: str) -> AsyncGenerator[SSEExecutionEventData, None]:  # noqa: ARG002
        try:
            while True:
                item = await self._exec_q.get()
                if item is None:
                    return
                yield item
        finally:
            self.exec_closed = True

    async def listen_notifications(self, user_id: str) -> AsyncGenerator[DomainNotificationSSEPayload, None]:  # noqa: ARG002
        try:
            while True:
                item = await self._notif_q.get()
                if item is None:
                    return
                yield item
        finally:
            self.notif_closed = True


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


def _make_service(bus: _FakeBus, exec_repo: _FakeExecRepo = _FakeExecRepo()) -> SSEService:
    return SSEService(
        bus=bus,  # type: ignore[arg-type]
        execution_repository=exec_repo,  # type: ignore[arg-type]
        logger=_test_logger,
    )


@pytest.mark.asyncio
async def test_execution_stream_prepends_status_from_db() -> None:
    execution = DomainExecution(execution_id="exec-1", status=ExecutionStatus.RUNNING)
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


@pytest.mark.asyncio
async def test_execution_stream_closes_on_terminal_event() -> None:
    bus = _FakeBus()
    svc = _make_service(bus, _FakeExecRepo(execution=DomainExecution(execution_id="exec-1", status=ExecutionStatus.RUNNING)))

    agen = await svc.create_execution_stream("exec-1", user_id="u1", user_role=UserRole.USER)

    # DB status prepend is always yielded first
    stat = await agen.__anext__()
    assert _decode(stat)["event_type"] == "status"

    await bus.push_exec(SSEExecutionEventData(
        event_type=EventType.EXECUTION_FAILED,
        execution_id="exec-1",
    ))
    failed = await agen.__anext__()
    assert _decode(failed)["event_type"] == EventType.EXECUTION_FAILED

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_execution_stream_enriches_result_stored() -> None:
    result = ExecutionResultDomain(
        execution_id="exec-2",
        status=ExecutionStatus.COMPLETED,
        exit_code=0,
        stdout="out",
        stderr="",
    )
    bus = _FakeBus()
    svc = _make_service(bus, _FakeExecRepo(execution=DomainExecution(execution_id="exec-2", status=ExecutionStatus.RUNNING), result=result))

    agen = await svc.create_execution_stream("exec-2", user_id="u1", user_role=UserRole.USER)

    # Consume DB status prepend
    await agen.__anext__()

    await bus.push_exec(SSEExecutionEventData(
        event_type=EventType.RESULT_STORED,
        execution_id="exec-2",
    ))
    evt = await agen.__anext__()
    data = _decode(evt)
    assert data["event_type"] == EventType.RESULT_STORED
    assert data["result"] is not None
    assert data["result"]["execution_id"] == "exec-2"

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_notification_stream_yields_notification_and_cleans_up() -> None:
    """Notification stream yields {"event": "notification", "data": ...} for each message."""
    bus = _FakeBus()
    svc = _make_service(bus)

    agen = svc.create_notification_stream(user_id="u1")

    await bus.push_notif(DomainNotificationSSEPayload(
        notification_id="n1",
        severity=NotificationSeverity.LOW,
        status=NotificationStatus.PENDING,
        tags=[],
        subject="s",
        body="b",
        action_url="",
        created_at=_NOW,
    ))

    notif = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    assert notif["event"] == "notification"
    data = json.loads(notif["data"])
    assert data["notification_id"] == "n1"
    assert data["subject"] == "s"
    assert data["channel"] == "in_app"

    await agen.aclose()
