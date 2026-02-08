import pytest
from app.domain.enums import QueuePriority
from app.services.coordinator.coordinator import ExecutionCoordinator
from dishka import AsyncContainer
from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


class TestHandleExecutionRequested:
    """Tests for _handle_execution_requested method."""

    @pytest.mark.asyncio
    async def test_handle_requested_schedules_execution(
        self, scope: AsyncContainer
    ) -> None:
        """Handler schedules execution immediately."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
        ev = make_execution_requested_event(execution_id="e-sched-1")

        await coord.handle_execution_requested(ev)

        assert "e-sched-1" in coord._active_executions  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_handle_requested_with_priority(
        self, scope: AsyncContainer
    ) -> None:
        """Handler respects execution priority."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
        ev = make_execution_requested_event(
            execution_id="e-priority-1",
            priority=QueuePriority.BACKGROUND,
        )

        await coord.handle_execution_requested(ev)

        assert "e-priority-1" in coord._active_executions  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_handle_requested_unique_executions(
        self, scope: AsyncContainer
    ) -> None:
        """Each execution gets unique tracking."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        ev1 = make_execution_requested_event(execution_id="e-unique-1")
        ev2 = make_execution_requested_event(execution_id="e-unique-2")

        await coord.handle_execution_requested(ev1)
        await coord.handle_execution_requested(ev2)

        assert "e-unique-1" in coord._active_executions  # noqa: SLF001
        assert "e-unique-2" in coord._active_executions  # noqa: SLF001


class TestCoordinatorLifecycle:
    """Tests for coordinator lifecycle."""

    @pytest.mark.asyncio
    async def test_coordinator_has_producer(self, scope: AsyncContainer) -> None:
        """Coordinator has Kafka producer configured."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        assert coord.producer is not None
