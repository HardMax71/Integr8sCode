import asyncio
import json
import structlog
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.metrics import ConnectionMetrics
from app.db.repositories import SSERepository
from app.domain.enums import EventType, ExecutionStatus
from app.domain.events import ResourceUsageDomain
from app.domain.execution import DomainExecution
from app.domain.sse import RedisNotificationMessage, SSEExecutionEventData, SSEExecutionStatusDomain
from app.services.sse import SSERedisBus, SSEService
from app.services.sse.redis_bus import _notif_msg_adapter, _sse_event_adapter
from app.settings import Settings

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.sse.sse_service")


class _FakeBus(SSERedisBus):
    def __init__(self) -> None:
        # Skip parent __init__
        self._exec_q: asyncio.Queue[SSEExecutionEventData | None] = asyncio.Queue()
        self._notif_q: asyncio.Queue[RedisNotificationMessage | None] = asyncio.Queue()
        self.notif_closed = False

    async def push_exec(self, data: dict[str, Any] | None) -> None:
        self._exec_q.put_nowait(_sse_event_adapter.validate_python(data) if data is not None else None)

    async def push_notif(self, data: dict[str, Any]) -> None:
        self._notif_q.put_nowait(_notif_msg_adapter.validate_python(data))

    async def listen_execution(self, execution_id: str) -> AsyncGenerator[SSEExecutionEventData, None]:  # noqa: ARG002
        while True:
            item = await self._exec_q.get()
            if item is None:
                return
            yield item

    async def listen_notifications(self, user_id: str) -> AsyncGenerator[RedisNotificationMessage, None]:  # noqa: ARG002
        try:
            while True:
                item = await self._notif_q.get()
                if item is None:
                    return
                yield item
        finally:
            self.notif_closed = True


class _FakeRepo(SSERepository):
    def __init__(self) -> None:
        # Skip parent __init__
        self.exec_for_result: DomainExecution | None = None

    async def get_execution_status(self, execution_id: str) -> SSEExecutionStatusDomain | None:
        return SSEExecutionStatusDomain(
            execution_id=execution_id,
            status=ExecutionStatus.RUNNING,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_execution(self, execution_id: str) -> DomainExecution | None:  # noqa: ARG002
        return self.exec_for_result



def _make_fake_settings() -> Settings:
    mock = MagicMock(spec=Settings)
    mock.SSE_HEARTBEAT_INTERVAL = 0
    return mock


def _decode(evt: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(evt["data"])
    return result


@pytest.mark.asyncio
async def test_execution_stream_closes_on_failed_event(connection_metrics: ConnectionMetrics) -> None:
    repo = _FakeRepo()
    bus = _FakeBus()
    svc = SSEService(repository=repo, sse_bus=bus,
                     settings=_make_fake_settings(), logger=_test_logger, connection_metrics=connection_metrics)

    agen = svc.create_execution_stream("exec-1", user_id="u1")

    # First event is now STATUS (no connected/subscribed preamble)
    stat = await agen.__anext__()
    assert _decode(stat)["event_type"] == "status"

    # Push a failed event and ensure stream ends after yielding it
    await bus.push_exec({"event_type": EventType.EXECUTION_FAILED, "execution_id": "exec-1"})
    failed = await agen.__anext__()
    assert _decode(failed)["event_type"] == EventType.EXECUTION_FAILED

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_execution_stream_result_stored_includes_result_payload(connection_metrics: ConnectionMetrics) -> None:
    repo = _FakeRepo()
    repo.exec_for_result = DomainExecution(
        execution_id="exec-2",
        script="",
        status=ExecutionStatus.COMPLETED,
        stdout="out",
        stderr="",
        lang="python",
        lang_version="3.11",
        resource_usage=ResourceUsageDomain(
            execution_time_wall_seconds=0.1, cpu_time_jiffies=1, clk_tck_hertz=100, peak_memory_kb=64
        ),
        user_id="u1",
        exit_code=0,
    )
    bus = _FakeBus()
    svc = SSEService(repository=repo, sse_bus=bus,
                     settings=_make_fake_settings(), logger=_test_logger, connection_metrics=connection_metrics)

    agen = svc.create_execution_stream("exec-2", user_id="u1")
    await agen.__anext__()  # status

    await bus.push_exec({"event_type": EventType.RESULT_STORED, "execution_id": "exec-2"})
    evt = await agen.__anext__()
    data = _decode(evt)
    assert data["event_type"] == EventType.RESULT_STORED
    assert "result" in data and data["result"]["execution_id"] == "exec-2"

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_notification_stream_yields_notification_and_cleans_up(connection_metrics: ConnectionMetrics) -> None:
    """Notification stream yields {"event": "notification", "data": ...} for each message.

    No control events (connected/subscribed/heartbeat) — those are handled by
    the SSE protocol layer (sse-starlette ping, EventSourcePlus onResponse).
    Cleanup happens via generator close (sse-starlette cancels on disconnect/shutdown).
    """
    repo = _FakeRepo()
    bus = _FakeBus()
    svc = SSEService(repository=repo, sse_bus=bus,
                     settings=_make_fake_settings(), logger=_test_logger, connection_metrics=connection_metrics)

    agen = svc.create_notification_stream("u1")

    # Push a notification payload before advancing (avoids blocking on empty queue)
    await bus.push_notif({
        "notification_id": "n1",
        "severity": "low",
        "status": "pending",
        "tags": [],
        "subject": "s",
        "body": "b",
        "action_url": "",
        "created_at": "2025-01-01T00:00:00Z",
    })

    notif = await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    # New format: SSE event field + JSON data (no event_type wrapper)
    assert notif["event"] == "notification"
    data = json.loads(notif["data"])
    assert data["notification_id"] == "n1"
    assert data["subject"] == "s"
    assert data["channel"] == "in_app"

    # Stop the stream by closing the generator (same as sse-starlette on disconnect)
    await agen.aclose()

    # Subscription should be closed during cleanup
    assert bus.notif_closed is True
