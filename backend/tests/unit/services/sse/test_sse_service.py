import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.db.repositories.sse_repository import SSERepository
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.execution import DomainExecution, ResourceUsageDomain
from app.domain.sse import ShutdownStatus, SSEExecutionStatusDomain, SSEHealthDomain
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus, SSERedisSubscription
from app.services.sse.sse_service import SSEService
from app.services.sse.sse_shutdown_manager import SSEShutdownManager
from app.settings import Settings
from pydantic import BaseModel

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.sse.sse_service")


class _FakeSubscription(SSERedisSubscription):
    def __init__(self) -> None:
        # Skip parent __init__ - no real Redis pubsub
        self._q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.closed = False

    async def get[T: BaseModel](self, model: type[T]) -> T | None:
        try:
            raw = await asyncio.wait_for(self._q.get(), timeout=0.5)
            if raw is None:
                return None
            return model.model_validate(raw)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def push(self, msg: dict[str, Any] | None) -> None:
        self._q.put_nowait(msg)

    async def close(self) -> None:
        self.closed = True


class _FakeBus(SSERedisBus):
    def __init__(self) -> None:
        # Skip parent __init__
        self.exec_sub = _FakeSubscription()
        self.notif_sub = _FakeSubscription()

    async def open_subscription(self, execution_id: str) -> SSERedisSubscription:  # noqa: ARG002
        return self.exec_sub

    async def open_notification_subscription(self, user_id: str) -> SSERedisSubscription:  # noqa: ARG002
        return self.notif_sub


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


class _FakeShutdown(SSEShutdownManager):
    def __init__(self) -> None:
        # Skip parent __init__
        self._evt = asyncio.Event()
        self._initiated = False
        self.registered: list[tuple[str, str]] = []
        self.unregistered: list[tuple[str, str]] = []

    async def register_connection(self, execution_id: str, connection_id: str) -> asyncio.Event:
        self.registered.append((execution_id, connection_id))
        return self._evt

    async def unregister_connection(self, execution_id: str, connection_id: str) -> None:
        self.unregistered.append((execution_id, connection_id))

    def is_shutting_down(self) -> bool:
        return self._initiated

    def get_shutdown_status(self) -> ShutdownStatus:
        return ShutdownStatus(
            phase="ready",
            initiated=self._initiated,
            complete=False,
            active_connections=0,
            draining_connections=0,
        )

    def initiate(self) -> None:
        self._initiated = True
        self._evt.set()


class _FakeRouter(SSEKafkaRedisBridge):
    def __init__(self) -> None:
        # Skip parent __init__
        pass

    def get_stats(self) -> dict[str, int | bool]:
        return {"num_consumers": 3, "active_executions": 2, "is_running": True, "total_buffers": 0}


def _make_fake_settings() -> Settings:
    mock = MagicMock(spec=Settings)
    mock.SSE_HEARTBEAT_INTERVAL = 0
    return mock


def _decode(evt: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(evt["data"])
    return result


@pytest.mark.asyncio
async def test_execution_stream_closes_on_failed_event() -> None:
    repo = _FakeRepo()
    bus = _FakeBus()
    sm = _FakeShutdown()
    svc = SSEService(repository=repo, router=_FakeRouter(), sse_bus=bus, shutdown_manager=sm,
                     settings=_make_fake_settings(), logger=_test_logger)

    agen = svc.create_execution_stream("exec-1", user_id="u1")
    first = await agen.__anext__()
    assert _decode(first)["event_type"] == "connected"

    # Should emit subscribed after Redis subscription is ready
    subscribed = await agen.__anext__()
    assert _decode(subscribed)["event_type"] == "subscribed"

    # Should emit initial status
    stat = await agen.__anext__()
    assert _decode(stat)["event_type"] == "status"

    # Push a failed event and ensure stream ends after yielding it
    await bus.exec_sub.push({"event_type": EventType.EXECUTION_FAILED, "execution_id": "exec-1", "data": {}})
    failed = await agen.__anext__()
    assert _decode(failed)["event_type"] == EventType.EXECUTION_FAILED

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_execution_stream_result_stored_includes_result_payload() -> None:
    repo = _FakeRepo()
    # DomainExecution with RU to_dict
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
    sm = _FakeShutdown()
    svc = SSEService(repository=repo, router=_FakeRouter(), sse_bus=bus, shutdown_manager=sm,
                     settings=_make_fake_settings(), logger=_test_logger)

    agen = svc.create_execution_stream("exec-2", user_id="u1")
    await agen.__anext__()  # connected
    await agen.__anext__()  # subscribed
    await agen.__anext__()  # status

    await bus.exec_sub.push({"event_type": EventType.RESULT_STORED, "execution_id": "exec-2", "data": {}})
    evt = await agen.__anext__()
    data = _decode(evt)
    assert data["event_type"] == EventType.RESULT_STORED
    assert "result" in data and data["result"]["execution_id"] == "exec-2"

    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


@pytest.mark.asyncio
async def test_notification_stream_connected_and_heartbeat_and_message() -> None:
    repo = _FakeRepo()
    bus = _FakeBus()
    sm = _FakeShutdown()
    settings = _make_fake_settings()
    settings.SSE_HEARTBEAT_INTERVAL = 0  # emit immediately
    svc = SSEService(repository=repo, router=_FakeRouter(), sse_bus=bus, shutdown_manager=sm, settings=settings,
                     logger=_test_logger)

    agen = svc.create_notification_stream("u1")
    connected = await agen.__anext__()
    assert _decode(connected)["event_type"] == "connected"

    # Should emit subscribed after Redis subscription is ready
    subscribed = await agen.__anext__()
    assert _decode(subscribed)["event_type"] == "subscribed"

    # With 0 interval, next yield should be heartbeat
    hb = await agen.__anext__()
    assert _decode(hb)["event_type"] == "heartbeat"

    # Push a notification payload (must match RedisNotificationMessage schema)
    await bus.notif_sub.push({
        "notification_id": "n1",
        "severity": "low",
        "status": "pending",
        "tags": [],
        "subject": "s",
        "body": "b",
        "action_url": "",
        "created_at": "2025-01-01T00:00:00Z",
    })
    notif = await agen.__anext__()
    assert _decode(notif)["event_type"] == "notification"

    # Stop the stream by initiating shutdown and advancing once more (loop checks flag)
    sm.initiate()
    # It may loop until it sees the flag; push a None to release get(timeout)
    await bus.notif_sub.push(None)
    # Give the generator a chance to observe the flag and finish
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(agen.__anext__(), timeout=0.2)


@pytest.mark.asyncio
async def test_health_status_shape() -> None:
    svc = SSEService(repository=_FakeRepo(), router=_FakeRouter(), sse_bus=_FakeBus(), shutdown_manager=_FakeShutdown(),
                     settings=_make_fake_settings(), logger=_test_logger)
    h = await svc.get_health_status()
    assert isinstance(h, SSEHealthDomain)
    assert h.active_consumers == 3 and h.active_executions == 2
