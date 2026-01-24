import uuid

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.execution import ExecutionStatus
from app.domain.execution import ResourceLimitsDomain
from app.domain.execution.exceptions import ExecutionNotFoundError
from app.services.execution_service import ExecutionService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


class TestGetResourceLimits:
    """Tests for get_k8s_resource_limits method."""

    @pytest.mark.asyncio
    async def test_get_k8s_resource_limits(self, scope: AsyncContainer) -> None:
        """Get K8s resource limits returns valid configuration."""
        svc: ExecutionService = await scope.get(ExecutionService)
        limits = await svc.get_k8s_resource_limits()

        assert isinstance(limits, ResourceLimitsDomain)
        assert limits.cpu_limit is not None
        assert limits.memory_limit is not None
        assert limits.cpu_request is not None
        assert limits.memory_request is not None
        assert limits.execution_timeout > 0
        assert isinstance(limits.supported_runtimes, dict)
        assert "python" in limits.supported_runtimes


class TestGetExampleScripts:
    """Tests for get_example_scripts method."""

    @pytest.mark.asyncio
    async def test_get_example_scripts(self, scope: AsyncContainer) -> None:
        """Get example scripts returns dictionary with python."""
        svc: ExecutionService = await scope.get(ExecutionService)
        examples = await svc.get_example_scripts()

        assert isinstance(examples, dict)
        assert "python" in examples
        assert isinstance(examples["python"], str)
        assert len(examples["python"]) > 0


class TestExecuteScript:
    """Tests for execute_script method."""

    @pytest.mark.asyncio
    async def test_execute_simple_script(self, scope: AsyncContainer) -> None:
        """Execute simple script creates execution and returns response."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        result = await svc.execute_script(
            script="print('hello world')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        assert result.execution_id is not None
        assert result.lang == "python"
        assert result.lang_version == "3.11"
        assert result.status in [
            ExecutionStatus.QUEUED,
            ExecutionStatus.SCHEDULED,
            ExecutionStatus.RUNNING,
        ]

    @pytest.mark.asyncio
    async def test_execute_script_with_custom_timeout(
        self, scope: AsyncContainer
    ) -> None:
        """Execute script with custom timeout override."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        result = await svc.execute_script(
            script="import time; time.sleep(1); print('done')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
            timeout_override=30,
        )

        assert result.execution_id is not None
        assert result.status in [
            ExecutionStatus.QUEUED,
            ExecutionStatus.SCHEDULED,
            ExecutionStatus.RUNNING,
        ]

    @pytest.mark.asyncio
    async def test_execute_script_returns_unique_ids(
        self, scope: AsyncContainer
    ) -> None:
        """Each execution gets unique ID."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        result1 = await svc.execute_script(
            script="print(1)",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        result2 = await svc.execute_script(
            script="print(2)",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        assert result1.execution_id != result2.execution_id


class TestGetExecutionResult:
    """Tests for get_execution_result method."""

    @pytest.mark.asyncio
    async def test_get_execution_result(self, scope: AsyncContainer) -> None:
        """Get execution result for existing execution."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Create execution
        exec_result = await svc.execute_script(
            script="print('test')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        # Get result
        result = await svc.get_execution_result(exec_result.execution_id)

        assert result.execution_id == exec_result.execution_id
        assert result.lang == "python"
        assert result.user_id == user_id

    @pytest.mark.asyncio
    async def test_get_execution_result_not_found(
        self, scope: AsyncContainer
    ) -> None:
        """Get nonexistent execution raises error."""
        svc: ExecutionService = await scope.get(ExecutionService)

        with pytest.raises(ExecutionNotFoundError):
            await svc.get_execution_result("nonexistent-execution-id")


class TestGetExecutionEvents:
    """Tests for get_execution_events method."""

    @pytest.mark.asyncio
    async def test_get_execution_events(self, scope: AsyncContainer) -> None:
        """Get events for execution returns list."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Create execution
        exec_result = await svc.execute_script(
            script="print('events test')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        # Get events
        events = await svc.get_execution_events(exec_result.execution_id)

        assert isinstance(events, list)
        # Should have at least EXECUTION_REQUESTED event
        if events:
            event_types = {e.event_type for e in events}
            assert EventType.EXECUTION_REQUESTED in event_types

    @pytest.mark.asyncio
    async def test_get_execution_events_with_filter(
        self, scope: AsyncContainer
    ) -> None:
        """Get events filtered by type."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        exec_result = await svc.execute_script(
            script="print('filter test')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        events = await svc.get_execution_events(
            exec_result.execution_id,
            event_types=[EventType.EXECUTION_REQUESTED],
        )

        assert isinstance(events, list)
        for event in events:
            assert event.event_type == EventType.EXECUTION_REQUESTED


class TestGetUserExecutions:
    """Tests for get_user_executions method."""

    @pytest.mark.asyncio
    async def test_get_user_executions(self, scope: AsyncContainer) -> None:
        """Get user executions returns list."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Create some executions
        for i in range(3):
            await svc.execute_script(
                script=f"print({i})",
                user_id=user_id,
                client_ip="127.0.0.1",
                user_agent="pytest",
                lang="python",
                lang_version="3.11",
            )

        # Get user executions
        executions = await svc.get_user_executions(user_id=user_id, limit=10, skip=0)

        assert isinstance(executions, list)
        assert len(executions) >= 3
        for execution in executions:
            assert execution.user_id == user_id

    @pytest.mark.asyncio
    async def test_get_user_executions_pagination(
        self, scope: AsyncContainer
    ) -> None:
        """Pagination works for user executions."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Create executions
        for i in range(5):
            await svc.execute_script(
                script=f"print({i})",
                user_id=user_id,
                client_ip="127.0.0.1",
                user_agent="pytest",
                lang="python",
                lang_version="3.11",
            )

        # Get first page
        page1 = await svc.get_user_executions(user_id=user_id, limit=2, skip=0)
        assert len(page1) == 2

        # Get second page
        page2 = await svc.get_user_executions(user_id=user_id, limit=2, skip=2)
        assert len(page2) == 2

        # Ensure different results
        page1_ids = {e.execution_id for e in page1}
        page2_ids = {e.execution_id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_get_user_executions_filter_by_language(
        self, scope: AsyncContainer
    ) -> None:
        """Filter executions by language."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        await svc.execute_script(
            script="print('python')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        executions = await svc.get_user_executions(
            user_id=user_id, lang="python", limit=10, skip=0
        )

        assert isinstance(executions, list)
        for execution in executions:
            assert execution.lang == "python"


class TestCountUserExecutions:
    """Tests for count_user_executions method."""

    @pytest.mark.asyncio
    async def test_count_user_executions(self, scope: AsyncContainer) -> None:
        """Count user executions returns correct count."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Get initial count
        initial_count = await svc.count_user_executions(user_id=user_id)

        # Create executions
        for _ in range(3):
            await svc.execute_script(
                script="print('count')",
                user_id=user_id,
                client_ip="127.0.0.1",
                user_agent="pytest",
                lang="python",
                lang_version="3.11",
            )

        # Count again
        new_count = await svc.count_user_executions(user_id=user_id)

        assert new_count == initial_count + 3


class TestDeleteExecution:
    """Tests for delete_execution method."""

    @pytest.mark.asyncio
    async def test_delete_execution(self, scope: AsyncContainer) -> None:
        """Delete execution removes it from database."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Create execution
        exec_result = await svc.execute_script(
            script="print('to delete')",
            user_id=user_id,
            client_ip="127.0.0.1",
            user_agent="pytest",
            lang="python",
            lang_version="3.11",
        )

        # Delete it
        deleted = await svc.delete_execution(exec_result.execution_id)
        assert deleted is True

        # Verify it's gone
        with pytest.raises(ExecutionNotFoundError):
            await svc.get_execution_result(exec_result.execution_id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_execution(
        self, scope: AsyncContainer
    ) -> None:
        """Delete nonexistent execution raises error."""
        svc: ExecutionService = await scope.get(ExecutionService)

        with pytest.raises(ExecutionNotFoundError):
            await svc.delete_execution("nonexistent-id")


class TestGetExecutionStats:
    """Tests for get_execution_stats method."""

    @pytest.mark.asyncio
    async def test_get_execution_stats(self, scope: AsyncContainer) -> None:
        """Get execution statistics for user."""
        svc: ExecutionService = await scope.get(ExecutionService)
        user_id = f"test_user_{uuid.uuid4().hex[:8]}"

        # Create some executions
        for i in range(2):
            await svc.execute_script(
                script=f"print({i})",
                user_id=user_id,
                client_ip="127.0.0.1",
                user_agent="pytest",
                lang="python",
                lang_version="3.11",
            )

        # Get stats
        stats = await svc.get_execution_stats(user_id=user_id)

        assert isinstance(stats, dict)
        assert "total" in stats
        assert stats["total"] >= 2
        assert "by_status" in stats
        assert "by_language" in stats
