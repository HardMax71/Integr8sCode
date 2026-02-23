import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from app.core.metrics.queue import QueueMetrics
from app.domain.enums import QueuePriority
from app.services.execution_queue import (
    _ACTIVE_KEY,
    _PENDING_KEYS,
    PRIORITY_ORDER,
    ExecutionQueueService,
    _pending_key,
)
from app.settings import Settings

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
def queue_service(mock_redis: AsyncMock, test_settings: Settings) -> ExecutionQueueService:
    logger = structlog.get_logger("test")
    metrics = QueueMetrics(test_settings)
    return ExecutionQueueService(mock_redis, logger, metrics)


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


@pytest.mark.asyncio
async def test_enqueue(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    event = make_execution_requested_event(execution_id="e1")
    position = await queue_service.enqueue(event)
    assert position == 0
    mock_redis.pipeline.assert_called()


@pytest.mark.asyncio
async def test_try_schedule_empty(queue_service: ExecutionQueueService) -> None:
    result = await queue_service.try_schedule(5)
    assert result is None


@pytest.mark.asyncio
async def test_try_schedule_returns_event(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    event = make_execution_requested_event(execution_id="e1")
    event_json = event.model_dump_json()

    script = AsyncMock(return_value=[b"e1", str(time.time() - 1.5).encode(), 0])
    mock_redis.register_script = MagicMock(return_value=script)
    mock_redis.get = AsyncMock(return_value=event_json)

    queue_service._schedule_script = None

    result = await queue_service.try_schedule(5)
    assert result is not None
    exec_id, returned_event = result
    assert exec_id == "e1"
    assert returned_event.execution_id == "e1"

    script.assert_called_once()
    keys = script.call_args.kwargs["keys"]
    assert keys[0] == _ACTIVE_KEY
    assert len(keys) == 1 + len(PRIORITY_ORDER)


@pytest.mark.asyncio
async def test_release(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    await queue_service.release("e1")
    mock_redis.pipeline.assert_called()


@pytest.mark.asyncio
async def test_update_priority_existing(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    script = AsyncMock(return_value=1)
    mock_redis.register_script = MagicMock(return_value=script)
    queue_service._update_priority_script = None
    result = await queue_service.update_priority("e1", QueuePriority.HIGH)
    assert result is True
    script.assert_called_once()


@pytest.mark.asyncio
async def test_update_priority_missing(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    script = AsyncMock(return_value=0)
    mock_redis.register_script = MagicMock(return_value=script)
    queue_service._update_priority_script = None
    result = await queue_service.update_priority("e1", QueuePriority.HIGH)
    assert result is False


@pytest.mark.asyncio
async def test_remove(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    # 5 ZREM results + 1 DELETE + 1 SREM
    pipe.execute = AsyncMock(return_value=[0, 0, 1, 0, 0, 1, 0])
    mock_redis.pipeline.return_value = pipe
    result = await queue_service.remove("e1")
    assert result is True


@pytest.mark.asyncio
async def test_remove_not_found(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[0, 0, 0, 0, 0, 0, 0])
    mock_redis.pipeline.return_value = pipe
    result = await queue_service.remove("e1")
    assert result is False


@pytest.mark.asyncio
async def test_get_queue_status(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    # 5 ZCARD results (one per priority) + 1 SCARD
    pipe.execute = AsyncMock(return_value=[1, 2, 3, 0, 1, 2])
    mock_redis.pipeline.return_value = pipe
    status = await queue_service.get_queue_status()
    assert status == {"queue_depth": 7, "active_count": 2}


@pytest.mark.asyncio
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
