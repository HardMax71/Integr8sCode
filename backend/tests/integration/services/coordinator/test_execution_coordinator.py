from collections.abc import Callable

import pytest
from app.services.coordinator.coordinator import ExecutionCoordinator
from dishka import AsyncContainer
from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_handle_requested_and_schedule(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
    execution_id = unique_id("exec-")
    ev = make_execution_requested_event(execution_id=execution_id)

    # Directly route requested event (no Kafka consumer)
    await coord._handle_execution_requested(ev)  # noqa: SLF001

    pos = await coord.queue_manager.get_queue_position(execution_id)
    assert pos is not None

    # Schedule one execution from queue
    next_ev = await coord.queue_manager.get_next_execution()
    assert next_ev is not None and next_ev.execution_id == execution_id
    await coord._schedule_execution(next_ev)  # noqa: SLF001
    # Should be tracked as active
    assert execution_id in coord._active_executions  # noqa: SLF001
