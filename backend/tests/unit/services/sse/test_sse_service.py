import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

pytestmark = pytest.mark.unit

from app.domain.enums.events import EventType
from app.domain.execution import DomainExecution, ResourceUsageDomain
from app.domain.sse import SSEHealthDomain
from app.services.sse.sse_service import SSEService


class _FakeSubscription:
    def __init__(self) -> None:
        self._q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.closed = False

    async def get(self, timeout: float = 0.5):  # noqa: ARG002
        try:
            return await asyncio.wait_for(self._q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def push(self, msg: dict[str, Any]) -> None:
        self._q.put_nowait(msg)

    async def close(self) -> None:
        self.closed = True


class _FakeBus:
    def __init__(self) -> None:
        self.exec_sub = _FakeSubscription()
        self.notif_sub = _FakeSubscription()

    async def open_subscription(self, execution_id: str) -> _FakeSubscription:  # noqa: ARG002
        return self.exec_sub

    async def open_notification_subscription(self, user_id: str) -> _FakeSubscription:  # noqa: ARG002
        return self.notif_sub


class _FakeRepo:
    class _Status:
        def __init__(self, execution_id: str) -> None:
            self.execution_id = execution_id
            self.status = "running"
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def __init__(self) -> None:
        self.exec_for_result: DomainExecution | None = None

    async def get_execution_status(self, execution_id: str) -> "_FakeRepo._Status":
        return _FakeRepo._Status(execution_id)

    async def get_execution(self, execution_id: str) -> DomainExecution | None:  # noqa: ARG002
        return self.exec_for_result


class _FakeShutdown:
    def __init__(self) -> None:
        self._evt = asyncio.Event()
        self._initiated = False
        self.registered: list[tuple[str, str]] = []
        self.unregistered: list[tuple[str, str]] = []

    async def register_connection(self, execution_id: str, connection_id: str):
        self.registered.append((execution_id, connection_id))
        return self._evt

    async def unregister_connection(self, execution_id: str, connection_id: str):
        self.unregistered.append((execution_id, connection_id))

    def is_shutting_down(self) -> bool:
        return self._initiated

    def get_shutdown_status(self) -> dict[str, Any]:
        return {"initiated": self._initiated, "phase": "ready"}

    def initiate(self) -> None:
        self._initiated = True
        self._evt.set()


class _FakeSettings:
    SSE_HEARTBEAT_INTERVAL = 0  # not used for execution; helpful for notification test


class _FakeRouter:
    def get_stats(self) -> dict[str, int | bool]:
        return {"num_consumers": 3, "active_executions": 2, "is_running": True, "total_buffers": 0}


def _decode(evt: dict[str, Any]) -> dict[str, Any]:
    import json

    return json.loads(evt["data"])  # type: ignore[index]


@pytest.mark.asyncio
async def test_execution_stream_closes_on_failed_event() -> None:
    repo = _FakeRepo()
    bus = _FakeBus()
    sm = _FakeShutdown()
    svc = SSEService(repository=repo, router=_FakeRouter(), sse_bus=bus, shutdown_manager=sm, settings=_FakeSettings())

    agen = svc.create_execution_stream("exec-1", user_id="u1")
    first = await agen.__anext__()
    assert _decode(first)["event_type"] == "connected"

    # Should emit initial status
    stat = await agen.__anext__()
    assert _decode(stat)["event_type"] == "status"

    # Push a failed event and ensure stream ends after yielding it
    await bus.exec_sub.push({"event_type": str(EventType.EXECUTION_FAILED), "execution_id": "exec-1", "data": {}})
    failed = await agen.__anext__()
    assert _decode(failed)["event_type"] == str(EventType.EXECUTION_FAILED)

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_execution_stream_result_stored_includes_result_payload() -> None:
    repo = _FakeRepo()
    # DomainExecution with RU to_dict
    repo.exec_for_result = DomainExecution(
        execution_id="exec-2",
        script="",
        status="completed",  # type: ignore[arg-type]
        stdout="out",
        stderr="",
        lang="python",
        lang_version="3.11",
        resource_usage=ResourceUsageDomain(0.1, 1, 100, 64),
        user_id="u1",
        exit_code=0,
    )
    bus = _FakeBus()
    sm = _FakeShutdown()
    svc = SSEService(repository=repo, router=_FakeRouter(), sse_bus=bus, shutdown_manager=sm, settings=_FakeSettings())

    agen = svc.create_execution_stream("exec-2", user_id="u1")
    await agen.__anext__()  # connected
    await agen.__anext__()  # status

    await bus.exec_sub.push({"event_type": str(EventType.RESULT_STORED), "execution_id": "exec-2", "data": {}})
    evt = await agen.__anext__()
    data = _decode(evt)
    assert data["event_type"] == str(EventType.RESULT_STORED)
    assert "result" in data and data["result"]["execution_id"] == "exec-2"

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_notification_stream_connected_and_heartbeat_and_message() -> None:
    repo = _FakeRepo()
    bus = _FakeBus()
    sm = _FakeShutdown()
    settings = _FakeSettings()
    settings.SSE_HEARTBEAT_INTERVAL = 0  # emit immediately
    svc = SSEService(repository=repo, router=_FakeRouter(), sse_bus=bus, shutdown_manager=sm, settings=settings)

    agen = svc.create_notification_stream("u1")
    connected = await agen.__anext__()
    assert _decode(connected)["event_type"] == "connected"

    # With 0 interval, next yield should be heartbeat
    hb = await agen.__anext__()
    assert _decode(hb)["event_type"] == "heartbeat"

    # Push a notification payload
    await bus.notif_sub.push({"notification_id": "n1", "subject": "s", "body": "b"})
    notif = await agen.__anext__()
    assert _decode(notif)["event_type"] == "notification"

    # Stop the stream by initiating shutdown and advancing once more (loop checks flag)
    sm.initiate()
    # It may loop until it sees the flag; push a None to release get(timeout)
    await bus.notif_sub.push(None)  # type: ignore[arg-type]
    # Give the generator a chance to observe the flag and finish
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), timeout=0.2)


@pytest.mark.asyncio
async def test_health_status_shape() -> None:
    svc = SSEService(repository=_FakeRepo(), router=_FakeRouter(), sse_bus=_FakeBus(), shutdown_manager=_FakeShutdown(), settings=_FakeSettings())
    h = await svc.get_health_status()
    assert isinstance(h, SSEHealthDomain)
    assert h.active_consumers == 3 and h.active_executions == 2
