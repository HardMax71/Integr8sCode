from __future__ import annotations

import asyncio
import structlog
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.core.metrics import ConnectionMetrics
from app.domain.enums import EventType, NotificationSeverity, NotificationStatus, ReplayStatus
from app.domain.sse import DomainNotificationSSEPayload, DomainReplaySSEPayload, SSEExecutionEventData
from app.services.sse import SSEService
from app.services.sse.sse_service import _exec_adapter, _notif_adapter, _replay_adapter

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.sse.publish")


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
    async def get_execution(self, execution_id: str) -> None:  # noqa: ARG002
        return None

    async def get_execution_result(self, execution_id: str) -> None:  # noqa: ARG002
        return None


def _make_service(fake_redis: _FakeRedis) -> SSEService:
    return SSEService(
        redis_client=fake_redis,  # type: ignore[arg-type]
        execution_repository=_FakeExecRepo(),  # type: ignore[arg-type]
        logger=_test_logger,
        connection_metrics=MagicMock(spec=ConnectionMetrics),
        poll_interval=0.01,
    )


@pytest.mark.asyncio
async def test_publish_event_writes_to_stream() -> None:
    r = _FakeRedis()
    svc = _make_service(r)

    evt = SSEExecutionEventData(
        event_type=EventType.EXECUTION_COMPLETED,
        execution_id="exec-1",
    )
    await svc.publish_event("exec-1", evt)

    stream = r._streams.get("sse:exec:exec-1")
    assert stream, "nothing written to stream"
    _, fields = stream[0]
    parsed = _exec_adapter.validate_json(fields[b"d"])
    assert parsed.event_type == EventType.EXECUTION_COMPLETED
    assert parsed.execution_id == "exec-1"


@pytest.mark.asyncio
async def test_publish_and_poll_round_trip() -> None:
    r = _FakeRedis()
    svc = _make_service(r)

    evt = SSEExecutionEventData(
        event_type=EventType.EXECUTION_COMPLETED,
        execution_id="exec-1",
    )
    await svc.publish_event("exec-1", evt)

    gen = svc._poll_stream("sse:exec:exec-1", _exec_adapter)
    msg = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert msg.event_type == EventType.EXECUTION_COMPLETED
    assert msg.execution_id == "exec-1"


@pytest.mark.asyncio
async def test_notification_publish_round_trip() -> None:
    r = _FakeRedis()
    svc = _make_service(r)

    notif = DomainNotificationSSEPayload(
        notification_id="n1",
        severity=NotificationSeverity.LOW,
        status=NotificationStatus.PENDING,
        tags=[],
        subject="test",
        body="body",
        action_url="",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    await svc.publish_notification("user-1", notif)

    stream = r._streams.get("sse:notif:user-1")
    assert stream, "nothing written to stream"
    _, fields = stream[0]
    parsed = _notif_adapter.validate_json(fields[b"d"])
    assert parsed.notification_id == "n1"


@pytest.mark.asyncio
async def test_replay_publish_round_trip() -> None:
    r = _FakeRedis()
    svc = _make_service(r)

    status = DomainReplaySSEPayload(
        session_id="sess-1",
        status=ReplayStatus.RUNNING,
        total_events=10,
        replayed_events=3,
        failed_events=0,
        skipped_events=0,
        replay_id="replay-1",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    await svc.publish_replay_status("sess-1", status)

    stream = r._streams.get("sse:replay:sess-1")
    assert stream, "nothing written to stream"
    _, fields = stream[0]
    parsed = _replay_adapter.validate_json(fields[b"d"])
    assert parsed.session_id == "sess-1"
    assert parsed.status == ReplayStatus.RUNNING
    assert parsed.replayed_events == 3
