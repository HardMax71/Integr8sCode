import pytest
from app.services.coordinator.coordinator import ExecutionCoordinator
from dishka import AsyncContainer
from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_handle_requested_and_schedule(scope: AsyncContainer) -> None:
    coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
    ev = make_execution_requested_event(execution_id="e-real-1")

    # Handler now schedules immediately - no polling needed
    await coord._handle_execution_requested(ev)  # noqa: SLF001

    # Execution should be active immediately after handler returns
    assert "e-real-1" in coord._active_executions  # noqa: SLF001
