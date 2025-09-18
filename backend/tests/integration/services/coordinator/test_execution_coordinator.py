import pytest

from app.services.coordinator.coordinator import ExecutionCoordinator
from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_handle_requested_and_schedule(scope) -> None:  # type: ignore[valid-type]
    coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
    ev = make_execution_requested_event(execution_id="e-real-1")

    # Directly route requested event (no Kafka consumer)
    await coord._handle_execution_requested(ev)  # noqa: SLF001

    pos = await coord.queue_manager.get_queue_position("e-real-1")
    assert pos is not None

    # Schedule one execution from queue
    next_ev = await coord.queue_manager.get_next_execution()
    assert next_ev is not None and next_ev.execution_id == "e-real-1"
    await coord._schedule_execution(next_ev)  # noqa: SLF001
    # Should be tracked as active
    assert "e-real-1" in coord._active_executions  # noqa: SLF001
