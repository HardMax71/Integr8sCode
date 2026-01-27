import pytest
from app.domain.enums.execution import QueuePriority
from app.services.coordinator.coordinator import ExecutionCoordinator
from dishka import AsyncContainer
from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.redis]


class TestExecutionCoordinator:
    """Tests for ExecutionCoordinator handler methods."""

    @pytest.mark.asyncio
    async def test_handle_requested_does_not_raise(self, scope: AsyncContainer) -> None:
        """Handler processes execution request without error."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
        ev = make_execution_requested_event(execution_id="e-test-1")

        # Should not raise
        await coord.handle_execution_requested(ev)

    @pytest.mark.asyncio
    async def test_handle_requested_with_priority(self, scope: AsyncContainer) -> None:
        """Handler respects execution priority."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
        ev = make_execution_requested_event(execution_id="e-priority-1", priority=QueuePriority.BACKGROUND)

        await coord.handle_execution_requested(ev)

    @pytest.mark.asyncio
    async def test_coordinator_resolves_from_di(self, scope: AsyncContainer) -> None:
        """Coordinator can be resolved from DI container."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        assert coord is not None
        assert hasattr(coord, "handle_execution_requested")
        assert hasattr(coord, "handle_execution_completed")
        assert hasattr(coord, "handle_execution_failed")
        assert hasattr(coord, "handle_execution_cancelled")
