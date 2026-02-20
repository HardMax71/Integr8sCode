import uuid

import pytest
import pytest_asyncio
from app.db.repositories import ExecutionRepository
from app.domain.enums import ExecutionStatus, QueuePriority
from app.domain.execution import DomainExecution, DomainExecutionCreate
from app.schemas_pydantic.admin_executions import (
    AdminExecutionListResponse,
    AdminExecutionResponse,
    QueueStatusResponse,
)
from dishka import AsyncContainer
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.admin]


@pytest_asyncio.fixture
async def stored_execution(scope: AsyncContainer) -> DomainExecution:
    """Insert a test execution directly into DB."""
    repo = await scope.get(ExecutionRepository)
    create_data = DomainExecutionCreate(
        script="print('hello')",
        user_id=f"test-user-{uuid.uuid4().hex[:8]}",
        lang="python",
        lang_version="3.11",
        status=ExecutionStatus.QUEUED,
        priority=QueuePriority.NORMAL,
    )
    return await repo.create_execution(create_data)


class TestListExecutions:
    """Tests for GET /api/v1/admin/executions/."""

    @pytest.mark.asyncio
    async def test_list_executions(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Admin can list executions."""
        response = await test_admin.get("/api/v1/admin/executions/")

        assert response.status_code == 200
        result = AdminExecutionListResponse.model_validate(response.json())
        assert result.total >= 1
        assert result.limit == 50
        assert result.skip == 0

    @pytest.mark.asyncio
    async def test_list_executions_with_status_filter(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Filter executions by status."""
        response = await test_admin.get(
            "/api/v1/admin/executions/", params={"status": "queued"},
        )

        assert response.status_code == 200
        result = AdminExecutionListResponse.model_validate(response.json())
        assert result.total >= 1
        for e in result.executions:
            assert e.status == ExecutionStatus.QUEUED

    @pytest.mark.asyncio
    async def test_list_executions_with_priority_filter(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Filter executions by priority."""
        response = await test_admin.get(
            "/api/v1/admin/executions/", params={"priority": "normal"},
        )

        assert response.status_code == 200
        result = AdminExecutionListResponse.model_validate(response.json())
        assert result.total >= 1
        for e in result.executions:
            assert e.priority == QueuePriority.NORMAL

    @pytest.mark.asyncio
    async def test_list_executions_with_user_id_filter(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Filter executions by user_id."""
        response = await test_admin.get(
            "/api/v1/admin/executions/",
            params={"user_id": stored_execution.user_id},
        )

        assert response.status_code == 200
        result = AdminExecutionListResponse.model_validate(response.json())
        assert result.total >= 1
        for e in result.executions:
            assert e.user_id == stored_execution.user_id

    @pytest.mark.asyncio
    async def test_list_executions_pagination(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Pagination params are forwarded correctly."""
        response = await test_admin.get(
            "/api/v1/admin/executions/", params={"skip": 0, "limit": 5},
        )

        assert response.status_code == 200
        result = AdminExecutionListResponse.model_validate(response.json())
        assert result.limit == 5
        assert result.skip == 0
        assert len(result.executions) <= 5

    @pytest.mark.asyncio
    async def test_list_executions_forbidden_for_regular_user(
        self, test_user: AsyncClient,
    ) -> None:
        """Regular user cannot list admin executions."""
        response = await test_user.get("/api/v1/admin/executions/")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_list_executions_unauthenticated(
        self, client: AsyncClient,
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/admin/executions/")
        assert response.status_code == 401


class TestUpdatePriority:
    """Tests for PUT /api/v1/admin/executions/{execution_id}/priority."""

    @pytest.mark.asyncio
    async def test_update_priority(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Admin can update execution priority."""
        response = await test_admin.put(
            f"/api/v1/admin/executions/{stored_execution.execution_id}/priority",
            json={"priority": "high"},
        )

        assert response.status_code == 200
        result = AdminExecutionResponse.model_validate(response.json())
        assert result.execution_id == stored_execution.execution_id
        assert result.priority == QueuePriority.HIGH

    @pytest.mark.asyncio
    async def test_update_priority_not_found(
        self, test_admin: AsyncClient,
    ) -> None:
        """Update priority for nonexistent execution returns 404."""
        response = await test_admin.put(
            "/api/v1/admin/executions/nonexistent-exec-id/priority",
            json={"priority": "high"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_priority_invalid_priority(
        self, test_admin: AsyncClient, stored_execution: DomainExecution,
    ) -> None:
        """Invalid priority value returns 422."""
        response = await test_admin.put(
            f"/api/v1/admin/executions/{stored_execution.execution_id}/priority",
            json={"priority": "invalid_value"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_priority_forbidden_for_regular_user(
        self, test_user: AsyncClient,
    ) -> None:
        """Regular user cannot update priority."""
        response = await test_user.put(
            "/api/v1/admin/executions/some-exec-id/priority",
            json={"priority": "high"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_priority_unauthenticated(
        self, client: AsyncClient,
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.put(
            "/api/v1/admin/executions/some-exec-id/priority",
            json={"priority": "high"},
        )
        assert response.status_code == 401


class TestGetQueueStatus:
    """Tests for GET /api/v1/admin/executions/queue."""

    @pytest.mark.asyncio
    async def test_get_queue_status(self, test_admin: AsyncClient) -> None:
        """Admin can get queue status."""
        response = await test_admin.get("/api/v1/admin/executions/queue")

        assert response.status_code == 200
        result = QueueStatusResponse.model_validate(response.json())
        assert result.queue_depth >= 0
        assert result.active_count >= 0
        assert result.max_concurrent >= 1
        assert isinstance(result.by_priority, dict)

    @pytest.mark.asyncio
    async def test_get_queue_status_forbidden_for_regular_user(
        self, test_user: AsyncClient,
    ) -> None:
        """Regular user cannot get queue status."""
        response = await test_user.get("/api/v1/admin/executions/queue")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_queue_status_unauthenticated(
        self, client: AsyncClient,
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/admin/executions/queue")
        assert response.status_code == 401
