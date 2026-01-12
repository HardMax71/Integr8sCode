import pytest
from app.services.coordinator.coordinator import ExecutionCoordinator
from dishka import AsyncContainer
from tests.helpers import make_execution_requested_event
from tests.helpers.eventually import eventually

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_handle_requested_and_schedule(scope: AsyncContainer) -> None:
    coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
    ev = make_execution_requested_event(execution_id="e-real-1")

    await coord._handle_execution_requested(ev)  # noqa: SLF001

    # Coordinator's background loop schedules executions automatically
    async def is_active() -> None:
        assert "e-real-1" in coord._active_executions  # noqa: SLF001

    await eventually(is_active, timeout=2.0, interval=0.05)
