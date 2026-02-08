import logging
from unittest.mock import AsyncMock

import pytest
from app.core.metrics import CoordinatorMetrics
from app.domain.enums import QueuePriority
from app.domain.events import ExecutionRequestedEvent
from app.services.coordinator.coordinator import ExecutionCoordinator, QueueRejectError

from tests.conftest import make_execution_requested_event

_test_logger = logging.getLogger("test.services.coordinator")

pytestmark = pytest.mark.unit


def _make_coordinator(
    coordinator_metrics: CoordinatorMetrics,
    *,
    max_queue_size: int = 100,
    max_executions_per_user: int = 100,
) -> ExecutionCoordinator:
    return ExecutionCoordinator(
        producer=AsyncMock(),
        execution_repository=AsyncMock(),
        logger=_test_logger,
        coordinator_metrics=coordinator_metrics,
        max_queue_size=max_queue_size,
        max_executions_per_user=max_executions_per_user,
    )


def _ev(execution_id: str, priority: QueuePriority = QueuePriority.NORMAL) -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id=execution_id, priority=priority)


@pytest.mark.asyncio
async def test_add_to_queue_returns_position(coordinator_metrics: CoordinatorMetrics) -> None:
    coord = _make_coordinator(coordinator_metrics)
    position = await coord._add_to_queue(_ev("a"))  # noqa: SLF001
    assert position == 0


@pytest.mark.asyncio
async def test_add_to_queue_rejects_when_full(coordinator_metrics: CoordinatorMetrics) -> None:
    coord = _make_coordinator(coordinator_metrics, max_queue_size=1)
    await coord._add_to_queue(_ev("a"))  # noqa: SLF001
    with pytest.raises(QueueRejectError, match="Queue is full"):
        await coord._add_to_queue(_ev("b"))  # noqa: SLF001


@pytest.mark.asyncio
async def test_add_to_queue_rejects_user_limit(coordinator_metrics: CoordinatorMetrics) -> None:
    coord = _make_coordinator(coordinator_metrics, max_executions_per_user=1)
    await coord._add_to_queue(_ev("a", priority=QueuePriority.NORMAL))  # noqa: SLF001
    with pytest.raises(QueueRejectError, match="User execution limit exceeded"):
        await coord._add_to_queue(_ev("b", priority=QueuePriority.NORMAL))  # noqa: SLF001


@pytest.mark.asyncio
async def test_pop_next_returns_highest_priority(coordinator_metrics: CoordinatorMetrics) -> None:
    coord = _make_coordinator(coordinator_metrics)
    await coord._add_to_queue(_ev("low", priority=QueuePriority.LOW))  # noqa: SLF001
    await coord._add_to_queue(_ev("critical", priority=QueuePriority.CRITICAL))  # noqa: SLF001
    await coord._add_to_queue(_ev("normal", priority=QueuePriority.NORMAL))  # noqa: SLF001

    first = await coord._pop_next()  # noqa: SLF001
    assert first is not None
    assert first.execution_id == "critical"

    second = await coord._pop_next()  # noqa: SLF001
    assert second is not None
    assert second.execution_id == "normal"


@pytest.mark.asyncio
async def test_pop_next_returns_none_when_empty(coordinator_metrics: CoordinatorMetrics) -> None:
    coord = _make_coordinator(coordinator_metrics)
    result = await coord._pop_next()  # noqa: SLF001
    assert result is None


@pytest.mark.asyncio
async def test_remove_from_queue(coordinator_metrics: CoordinatorMetrics) -> None:
    coord = _make_coordinator(coordinator_metrics)
    await coord._add_to_queue(_ev("a"))  # noqa: SLF001
    await coord._add_to_queue(_ev("b"))  # noqa: SLF001

    removed = await coord._remove_from_queue("a")  # noqa: SLF001
    assert removed is True

    result = await coord._pop_next()  # noqa: SLF001
    assert result is not None
    assert result.execution_id == "b"
