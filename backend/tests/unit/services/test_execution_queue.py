import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from redis.exceptions import ConnectionError as RedisConnectionError

from app.domain.enums import QueuePriority
from app.services.execution_queue import (
    _EVENT_TTL,
    _PENDING_KEYS,
    _PROVISIONAL_SLOT_SECONDS,
    _RUNNING_KEY,
    _SLOT_GRACE_SECONDS,
    PRIORITY_ORDER,
    ExecutionQueueService,
    _owner_key,
    _pending_key,
    _user_key,
)
from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_redis() -> AsyncMock:
    r = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, True])
    r.pipeline = MagicMock(return_value=pipe)
    r.zrank = AsyncMock(return_value=0)
    r.register_script = MagicMock(return_value=AsyncMock(return_value=None))
    return r


@pytest.fixture
def queue_service(mock_redis: AsyncMock, tracer: trace.Tracer) -> ExecutionQueueService:
    return ExecutionQueueService(mock_redis, structlog.get_logger("test"), tracer)


def test_priority_order() -> None:
    """PRIORITY_ORDER lists priorities from highest to lowest."""
    assert PRIORITY_ORDER[0] == QueuePriority.CRITICAL
    assert PRIORITY_ORDER[-1] == QueuePriority.BACKGROUND
    assert len(PRIORITY_ORDER) == len(QueuePriority)


def test_pending_keys_match_priority_order() -> None:
    """Each priority has a dedicated pending sorted set key."""
    for priority, key in zip(PRIORITY_ORDER, _PENDING_KEYS, strict=True):
        assert key == _pending_key(priority)
        assert priority in key


async def test_enqueue(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock, span_exporter: InMemorySpanExporter
) -> None:
    event = make_execution_requested_event(execution_id="e1", priority=QueuePriority.HIGH)
    position = await queue_service.enqueue(event)
    assert position == 0
    mock_redis.pipeline.assert_called()
    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == ("queue.enqueue", {"queue.priority": QueuePriority.HIGH})


async def test_try_schedule_empty(queue_service: ExecutionQueueService, span_exporter: InMemorySpanExporter) -> None:
    result = await queue_service.try_schedule(5)
    assert result is None
    assert span_exporter.get_finished_spans() == ()


async def test_try_schedule_returns_event(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock, span_exporter: InMemorySpanExporter
) -> None:
    event = make_execution_requested_event(execution_id="e1")
    event_json = event.model_dump_json()

    enqueued_at = time.time() - 1.5
    script = AsyncMock(return_value=[b"e1", str(enqueued_at).encode(), 0])
    mock_redis.register_script = MagicMock(return_value=script)
    mock_redis.get = AsyncMock(return_value=event_json)

    queue_service._schedule_script = None

    before = time.time()
    result = await queue_service.try_schedule(5)
    after = time.time()
    assert result is not None
    exec_id, returned_event = result
    assert exec_id == "e1"
    assert returned_event.execution_id == "e1"

    script.assert_called_once()
    keys = script.call_args.kwargs["keys"]
    assert keys[0] == _RUNNING_KEY
    assert len(keys) == 1 + len(PRIORITY_ORDER)
    max_active, now, provisional = script.call_args.kwargs["args"]
    assert max_active == 5
    assert provisional - now == _PROVISIONAL_SLOT_SECONDS

    calls = mock_redis.pipeline.return_value.zadd.call_args_list
    assert [c.args[0] for c in calls] == [_RUNNING_KEY, _user_key(event.metadata.user_id)]
    slot = event.timeout_seconds + _SLOT_GRACE_SECONDS
    assert before + slot <= calls[0].args[1]["e1"] <= after + slot
    assert calls[1].args[1] == calls[0].args[1]
    assert [c.kwargs for c in calls] == [{"xx": True}, {"xx": True}]

    [span] = span_exporter.get_finished_spans()
    assert span.name == "queue.schedule"
    assert span.attributes is not None
    assert span.attributes["queue.outcome"] == "scheduled"
    assert span.attributes["queue.priority"] == PRIORITY_ORDER[0]
    wait_seconds = span.attributes["queue.wait_seconds"]
    assert isinstance(wait_seconds, float)
    assert before - enqueued_at <= wait_seconds <= after - enqueued_at


async def test_try_schedule_event_data_expired(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock, span_exporter: InMemorySpanExporter
) -> None:
    """When the event JSON has expired from Redis, try_schedule frees the running slot and returns None."""
    script = AsyncMock(return_value=[b"e-gone", str(time.time()).encode(), 2])
    mock_redis.register_script = MagicMock(return_value=script)
    mock_redis.get = AsyncMock(return_value=None)
    queue_service._schedule_script = None

    result = await queue_service.try_schedule(5)

    assert result is None
    mock_redis.zrem.assert_awaited_once_with(_RUNNING_KEY, "e-gone")
    mock_redis.get.assert_any_await(_owner_key("e-gone"))
    [span] = span_exporter.get_finished_spans()
    assert (span.name, span.attributes) == (
        "queue.schedule",
        {"queue.priority": PRIORITY_ORDER[2], "queue.outcome": "event_data_lost"},
    )


async def test_release(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    await queue_service.release("e1")
    mock_redis.pipeline.assert_called()


async def test_update_priority_existing(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    script = AsyncMock(return_value=1)
    mock_redis.register_script = MagicMock(return_value=script)
    queue_service._update_priority_script = None
    result = await queue_service.update_priority("e1", QueuePriority.HIGH)
    assert result is True
    script.assert_called_once()


async def test_update_priority_missing(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    script = AsyncMock(return_value=0)
    mock_redis.register_script = MagicMock(return_value=script)
    queue_service._update_priority_script = None
    result = await queue_service.update_priority("e1", QueuePriority.HIGH)
    assert result is False


async def test_remove(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    # 5 ZREM results + 1 DELETE (event) + 1 DELETE (retry) + 1 SREM
    pipe.execute = AsyncMock(return_value=[0, 0, 1, 0, 0, 1, 0])
    mock_redis.pipeline.return_value = pipe
    result = await queue_service.remove("e1")
    assert result is True


async def test_remove_not_found(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[0, 0, 0, 0, 0, 0, 0])
    mock_redis.pipeline.return_value = pipe
    result = await queue_service.remove("e1")
    assert result is False


async def test_get_queue_status(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    # 5 ZCARD results (one per priority) + 1 SCARD
    pipe.execute = AsyncMock(return_value=[1, 2, 3, 0, 1, 2])
    mock_redis.pipeline.return_value = pipe
    status = await queue_service.get_queue_status()
    assert status == {"queue_depth": 7, "active_count": 2}


async def test_get_pending_by_priority(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    # ZCARD per priority: critical=0, high=2, normal=3, low=0, background=1
    pipe.execute = AsyncMock(return_value=[0, 2, 3, 0, 1])
    mock_redis.pipeline.return_value = pipe
    counts = await queue_service.get_pending_by_priority()
    assert QueuePriority.HIGH in counts
    assert counts[QueuePriority.HIGH] == 2
    assert counts[QueuePriority.NORMAL] == 3
    assert counts[QueuePriority.BACKGROUND] == 1
    assert QueuePriority.CRITICAL not in counts
    assert QueuePriority.LOW not in counts


@pytest.mark.parametrize(("script_result", "expected"), [(1, True), (0, False)])
async def test_reserve_user_slot(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock, script_result: int, expected: bool
) -> None:
    script = AsyncMock(return_value=script_result)
    mock_redis.register_script = MagicMock(return_value=script)

    assert await queue_service.reserve_user_slot("u1", "e1", 3) is expected

    assert script.call_args.kwargs["keys"] == [_user_key("u1"), _owner_key("e1")]
    _, limit, ttl, exec_id, user_id = script.call_args.kwargs["args"]
    assert (limit, exec_id, user_id) == (3, "e1", "u1")
    assert ttl == _EVENT_TTL


async def test_release_user_slot_removes_the_owners_entry(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock
) -> None:
    mock_redis.get = AsyncMock(return_value=b"u1")

    await queue_service.release_user_slot("e1")

    pipe = mock_redis.pipeline.return_value
    pipe.zrem.assert_called_once_with(_user_key("u1"), "e1")
    pipe.delete.assert_called_once_with(_owner_key("e1"))


async def test_release_user_slot_without_an_owner_is_a_no_op(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock
) -> None:
    mock_redis.get = AsyncMock(return_value=None)

    await queue_service.release_user_slot("e1")

    mock_redis.pipeline.assert_not_called()


async def test_release_user_slot_survives_a_redis_error(
    queue_service: ExecutionQueueService, mock_redis: AsyncMock
) -> None:
    mock_redis.get = AsyncMock(side_effect=RedisConnectionError("down"))

    await queue_service.release_user_slot("e1")
