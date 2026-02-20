from unittest.mock import AsyncMock

import pytest
import structlog
from app.db.repositories import ExecutionRepository
from app.domain.admin.settings_models import SystemSettings
from app.domain.enums import ExecutionStatus, QueuePriority
from app.domain.execution import ExecutionNotFoundError
from app.services.admin import AdminExecutionService
from app.services.execution_queue import ExecutionQueueService
from app.services.runtime_settings import RuntimeSettingsLoader

from tests.unit.conftest import make_domain_execution

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock(spec=ExecutionRepository)
    repo.get_executions = AsyncMock(return_value=[])
    repo.count_executions = AsyncMock(return_value=0)
    repo.update_priority = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_queue() -> AsyncMock:
    q = AsyncMock(spec=ExecutionQueueService)
    q.update_priority = AsyncMock(return_value=True)
    q.get_queue_status = AsyncMock(return_value={"queue_depth": 5, "active_count": 2})
    q.get_pending_by_priority = AsyncMock(return_value={QueuePriority.NORMAL: 3})
    return q


@pytest.fixture
def mock_runtime_settings() -> AsyncMock:
    rs = AsyncMock(spec=RuntimeSettingsLoader)
    rs.get_effective_settings = AsyncMock(return_value=SystemSettings(max_concurrent_executions=10))
    return rs


@pytest.fixture
def service(
    mock_repo: AsyncMock, mock_queue: AsyncMock, mock_runtime_settings: AsyncMock,
) -> AdminExecutionService:
    logger = structlog.get_logger("test")
    return AdminExecutionService(mock_repo, mock_queue, mock_runtime_settings, logger)


class TestListExecutions:
    @pytest.mark.asyncio
    async def test_list_executions_no_filters(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        execs = [make_domain_execution()]
        mock_repo.get_executions.return_value = execs
        mock_repo.count_executions.return_value = 1

        result, total = await service.list_executions()

        assert result == execs
        assert total == 1
        mock_repo.get_executions.assert_awaited_once_with(
            query={}, limit=50, skip=0, sort=[("created_at", -1)],
        )
        mock_repo.count_executions.assert_awaited_once_with({})

    @pytest.mark.asyncio
    async def test_list_executions_with_status(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        await service.list_executions(status=ExecutionStatus.RUNNING)
        mock_repo.get_executions.assert_awaited_once()
        call_kwargs = mock_repo.get_executions.call_args
        assert call_kwargs.kwargs["query"] == {"status": ExecutionStatus.RUNNING}

    @pytest.mark.asyncio
    async def test_list_executions_with_priority(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        await service.list_executions(priority=QueuePriority.HIGH)
        call_kwargs = mock_repo.get_executions.call_args
        assert call_kwargs.kwargs["query"] == {"priority": QueuePriority.HIGH}

    @pytest.mark.asyncio
    async def test_list_executions_with_user_id(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        await service.list_executions(user_id="u1")
        call_kwargs = mock_repo.get_executions.call_args
        assert call_kwargs.kwargs["query"] == {"user_id": "u1"}

    @pytest.mark.asyncio
    async def test_list_executions_with_all_filters(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        await service.list_executions(
            status=ExecutionStatus.QUEUED,
            priority=QueuePriority.HIGH,
            user_id="u1",
        )
        call_kwargs = mock_repo.get_executions.call_args
        assert call_kwargs.kwargs["query"] == {
            "status": ExecutionStatus.QUEUED,
            "priority": QueuePriority.HIGH,
            "user_id": "u1",
        }

    @pytest.mark.asyncio
    async def test_list_executions_pagination(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        await service.list_executions(limit=10, skip=20)
        call_kwargs = mock_repo.get_executions.call_args
        assert call_kwargs.kwargs["limit"] == 10
        assert call_kwargs.kwargs["skip"] == 20


class TestUpdatePriority:
    @pytest.mark.asyncio
    async def test_update_priority_success(
        self, service: AdminExecutionService, mock_repo: AsyncMock, mock_queue: AsyncMock,
    ) -> None:
        updated_exec = make_domain_execution(priority=QueuePriority.HIGH)
        mock_repo.update_priority.return_value = updated_exec

        result = await service.update_priority("e1", QueuePriority.HIGH)

        assert result == updated_exec
        assert result.priority == QueuePriority.HIGH
        mock_repo.update_priority.assert_awaited_once_with("e1", QueuePriority.HIGH)

    @pytest.mark.asyncio
    async def test_update_priority_not_found(
        self, service: AdminExecutionService, mock_repo: AsyncMock,
    ) -> None:
        mock_repo.update_priority.return_value = None

        with pytest.raises(ExecutionNotFoundError):
            await service.update_priority("missing", QueuePriority.HIGH)

    @pytest.mark.asyncio
    async def test_update_priority_updates_redis(
        self, service: AdminExecutionService, mock_repo: AsyncMock, mock_queue: AsyncMock,
    ) -> None:
        mock_repo.update_priority.return_value = make_domain_execution(priority=QueuePriority.CRITICAL)

        await service.update_priority("e1", QueuePriority.CRITICAL)

        mock_queue.update_priority.assert_awaited_once_with("e1", QueuePriority.CRITICAL)


class TestGetQueueStatus:
    @pytest.mark.asyncio
    async def test_get_queue_status(
        self, service: AdminExecutionService,
        mock_queue: AsyncMock, mock_runtime_settings: AsyncMock,
    ) -> None:
        result = await service.get_queue_status()

        assert result["queue_depth"] == 5
        assert result["active_count"] == 2
        assert result["max_concurrent"] == 10
        assert result["by_priority"] == {QueuePriority.NORMAL: 3}
        mock_queue.get_queue_status.assert_awaited_once()
        mock_queue.get_pending_by_priority.assert_awaited_once()
        mock_runtime_settings.get_effective_settings.assert_awaited_once()
