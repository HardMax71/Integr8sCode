from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

from app.core.metrics.queue import QueueMetrics
from app.domain.enums import QueuePriority
from app.services.execution_queue import (
    PRIORITY_SCORES,
    ExecutionQueueService,
    _ACTIVE_KEY,
    _PENDING_KEY,
    _event_key,
    _score_for,
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


def test_score_ordering() -> None:
    """Higher-priority items have lower scores."""
    scores = {p: PRIORITY_SCORES[p] for p in QueuePriority}
    assert scores[QueuePriority.CRITICAL] < scores[QueuePriority.NORMAL]
    assert scores[QueuePriority.NORMAL] < scores[QueuePriority.BACKGROUND]


def test_score_for_same_priority_increases() -> None:
    """Two calls with the same priority produce increasing scores (FIFO)."""
    s1 = _score_for(QueuePriority.NORMAL)
    s2 = _score_for(QueuePriority.NORMAL)
    assert s2 >= s1


def test_score_for_higher_priority_lower_score() -> None:
    """CRITICAL score band is strictly below NORMAL score band."""
    critical_max = (PRIORITY_SCORES[QueuePriority.CRITICAL] + 1) * 10**12 - 1
    normal_min = PRIORITY_SCORES[QueuePriority.NORMAL] * 10**12
    assert critical_max < normal_min


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

    script = AsyncMock(return_value=b"e1")
    mock_redis.register_script = MagicMock(return_value=script)
    mock_redis.get = AsyncMock(return_value=event_json)

    # Reset the cached script
    queue_service._schedule_script = None

    result = await queue_service.try_schedule(5)
    assert result is not None
    exec_id, returned_event = result
    assert exec_id == "e1"
    assert returned_event.execution_id == "e1"


@pytest.mark.asyncio
async def test_release(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    await queue_service.release("e1")
    mock_redis.pipeline.assert_called()


@pytest.mark.asyncio
async def test_update_priority_existing(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    mock_redis.zscore = AsyncMock(return_value=200.0)
    mock_redis.zadd = AsyncMock(return_value=0)
    result = await queue_service.update_priority("e1", QueuePriority.HIGH)
    assert result is True


@pytest.mark.asyncio
async def test_update_priority_missing(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    mock_redis.zscore = AsyncMock(return_value=None)
    result = await queue_service.update_priority("e1", QueuePriority.HIGH)
    assert result is False


@pytest.mark.asyncio
async def test_remove(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[1, 1, 0])
    mock_redis.pipeline.return_value = pipe
    result = await queue_service.remove("e1")
    assert result is True


@pytest.mark.asyncio
async def test_remove_not_found(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[0, 0, 0])
    mock_redis.pipeline.return_value = pipe
    result = await queue_service.remove("e1")
    assert result is False


@pytest.mark.asyncio
async def test_get_queue_status(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[5, 2])
    mock_redis.pipeline.return_value = pipe
    status = await queue_service.get_queue_status()
    assert status == {"queue_depth": 5, "active_count": 2}


@pytest.mark.asyncio
async def test_get_pending_by_priority(queue_service: ExecutionQueueService, mock_redis: AsyncMock) -> None:
    mock_redis.zcount = AsyncMock(side_effect=[0, 2, 3, 0, 1])
    counts = await queue_service.get_pending_by_priority()
    assert QueuePriority.HIGH in counts
    assert counts[QueuePriority.HIGH] == 2
    assert counts[QueuePriority.NORMAL] == 3
    assert counts[QueuePriority.BACKGROUND] == 1
    assert QueuePriority.CRITICAL not in counts
