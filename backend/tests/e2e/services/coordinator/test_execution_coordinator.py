import pytest
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

        await coord._handle_execution_requested(ev)  # noqa: SLF001

        assert "e-sched-1" in coord._active_executions  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_handle_requested_with_priority(
        self, scope: AsyncContainer
    ) -> None:
        """Handler respects execution priority."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
        ev = make_execution_requested_event(
            execution_id="e-priority-1",
            priority=10,  # High priority
        )

        await coord._handle_execution_requested(ev)  # noqa: SLF001

        assert "e-priority-1" in coord._active_executions  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_handle_requested_unique_executions(
        self, scope: AsyncContainer
    ) -> None:
        """Each execution gets unique tracking."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        ev1 = make_execution_requested_event(execution_id="e-unique-1")
        ev2 = make_execution_requested_event(execution_id="e-unique-2")

        await coord._handle_execution_requested(ev1)  # noqa: SLF001
        await coord._handle_execution_requested(ev2)  # noqa: SLF001

        assert "e-unique-1" in coord._active_executions  # noqa: SLF001
        assert "e-unique-2" in coord._active_executions  # noqa: SLF001


class TestGetStatus:
    """Tests for get_status method."""

    @pytest.mark.asyncio
    async def test_get_status_returns_dict(self, scope: AsyncContainer) -> None:
        """Get status returns dictionary with coordinator info."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        status = await coord.get_status()

        assert isinstance(status, dict)
        assert "running" in status
        assert "active_executions" in status
        assert "queue_stats" in status
        assert "resource_stats" in status

    @pytest.mark.asyncio
    async def test_get_status_tracks_active_executions(
        self, scope: AsyncContainer
    ) -> None:
        """Status tracks number of active executions."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        initial_status = await coord.get_status()
        initial_active = initial_status.get("active_executions", 0)

        # Add execution
        ev = make_execution_requested_event(execution_id="e-status-track-1")
        await coord._handle_execution_requested(ev)  # noqa: SLF001

        new_status = await coord.get_status()
        new_active = new_status.get("active_executions", 0)

        assert new_active == initial_active + 1, (
            f"Expected exactly one more active execution: {initial_active} -> {new_active}"
        )


class TestQueueManager:
    """Tests for queue manager integration."""

    @pytest.mark.asyncio
    async def test_queue_manager_initialized(self, scope: AsyncContainer) -> None:
        """Queue manager is properly initialized."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        assert coord.queue_manager is not None
        assert hasattr(coord.queue_manager, "add_execution")
        assert hasattr(coord.queue_manager, "get_next_execution")


class TestResourceManager:
    """Tests for resource manager integration."""

    @pytest.mark.asyncio
    async def test_resource_manager_initialized(
        self, scope: AsyncContainer
    ) -> None:
        """Resource manager is properly initialized."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        assert coord.resource_manager is not None
        assert hasattr(coord.resource_manager, "request_allocation")
        assert hasattr(coord.resource_manager, "release_allocation")

    @pytest.mark.asyncio
    async def test_resource_manager_has_pool(
        self, scope: AsyncContainer
    ) -> None:
        """Resource manager has resource pool configured."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        # Check resource manager has pool with capacity
        assert coord.resource_manager.pool is not None
        assert coord.resource_manager.pool.total_cpu_cores > 0
        assert coord.resource_manager.pool.total_memory_mb > 0


class TestCoordinatorLifecycle:
    """Tests for coordinator lifecycle."""

    @pytest.mark.asyncio
    async def test_coordinator_has_consumer(self, scope: AsyncContainer) -> None:
        """Coordinator has Kafka consumer configured."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        # Consumer is set up during start, may be None before
        assert hasattr(coord, "consumer")

    @pytest.mark.asyncio
    async def test_coordinator_has_producer(self, scope: AsyncContainer) -> None:
        """Coordinator has Kafka producer configured."""
        coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)

        assert coord.producer is not None
