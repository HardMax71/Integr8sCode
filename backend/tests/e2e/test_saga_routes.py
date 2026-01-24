import asyncio

import pytest
from app.domain.enums.saga import SagaState
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.saga import (
    SagaCancellationResponse,
    SagaListResponse,
    SagaStatusResponse,
)
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


async def wait_for_saga(
        client: AsyncClient,
        execution_id: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
) -> SagaStatusResponse:
    """Poll until at least one saga exists for the execution.

    Args:
        client: Authenticated HTTP client
        execution_id: ID of execution to get saga for
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        First saga for the execution

    Raises:
        TimeoutError: If no saga appears within timeout
        AssertionError: If API returns unexpected status code
    """
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(f"/api/v1/sagas/execution/{execution_id}")
        assert response.status_code == 200, f"Unexpected: {response.status_code} - {response.text}"

        result = SagaListResponse.model_validate(response.json())
        if result.sagas:
            return result.sagas[0]

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"No saga appeared for execution {execution_id} within {timeout}s")


class TestGetSagaStatus:
    """Tests for GET /api/v1/sagas/{saga_id}."""

    @pytest.mark.asyncio
    async def test_get_saga_status(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get saga status by ID returns valid response."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get(f"/api/v1/sagas/{saga.saga_id}")

        assert response.status_code == 200
        result = SagaStatusResponse.model_validate(response.json())
        assert result.saga_id == saga.saga_id
        assert result.execution_id == created_execution.execution_id
        assert result.state in list(SagaState)
        assert result.saga_name is not None
        assert result.created_at is not None
        assert result.updated_at is not None
        assert result.retry_count >= 0

    @pytest.mark.asyncio
    async def test_get_saga_not_found(self, test_user: AsyncClient) -> None:
        """Get nonexistent saga returns 404."""
        response = await test_user.get("/api/v1/sagas/nonexistent-saga-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_saga_access_denied(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            created_execution: ExecutionResponse,
    ) -> None:
        """Cannot access another user's saga."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await another_user.get(f"/api/v1/sagas/{saga.saga_id}")

        assert response.status_code == 403


class TestGetExecutionSagas:
    """Tests for GET /api/v1/sagas/execution/{execution_id}."""

    @pytest.mark.asyncio
    async def test_get_execution_sagas(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get sagas for a specific execution."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}"
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert result.total >= 1
        assert len(result.sagas) >= 1
        assert isinstance(result.has_more, bool)

        saga_ids = [s.saga_id for s in result.sagas]
        assert saga.saga_id in saga_ids

    @pytest.mark.asyncio
    async def test_get_execution_sagas_with_pagination(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Pagination works for execution sagas."""
        await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}",
            params={"limit": 5, "skip": 0},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())
        assert result.limit == 5
        assert result.skip == 0

    @pytest.mark.asyncio
    async def test_get_execution_sagas_with_state_filter(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Filter sagas by state."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}",
            params={"state": saga.state.value},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())
        assert len(result.sagas) >= 1
        for s in result.sagas:
            assert s.state == saga.state


class TestListSagas:
    """Tests for GET /api/v1/sagas/."""

    @pytest.mark.asyncio
    async def test_list_sagas(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """List sagas for current user."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get("/api/v1/sagas/")

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert result.total >= 1
        assert len(result.sagas) >= 1

        saga_ids = [s.saga_id for s in result.sagas]
        assert saga.saga_id in saga_ids

    @pytest.mark.asyncio
    async def test_list_sagas_with_state_filter(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Filter sagas by state."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get(
            "/api/v1/sagas/",
            params={"state": saga.state.value},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        for s in result.sagas:
            assert s.state == saga.state

    @pytest.mark.asyncio
    async def test_list_sagas_pagination(
            self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Pagination works for saga list."""
        await wait_for_saga(test_user, created_execution.execution_id)

        response = await test_user.get(
            "/api/v1/sagas/",
            params={"limit": 10, "skip": 0},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())
        assert result.limit == 10
        assert result.skip == 0

    @pytest.mark.asyncio
    async def test_list_sagas_unauthenticated(
            self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/sagas/")

        assert response.status_code == 401


class TestCancelSaga:
    """Tests for POST /api/v1/sagas/{saga_id}/cancel."""

    @pytest.mark.asyncio
    async def test_cancel_saga(
            self,
            test_user: AsyncClient,
            long_running_execution_request: ExecutionRequest,
    ) -> None:
        """Cancel a running saga."""
        exec_response = await test_user.post(
            "/api/v1/execute", json=long_running_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution = ExecutionResponse.model_validate(exec_response.json())
        saga = await wait_for_saga(test_user, execution.execution_id)

        response = await test_user.post(f"/api/v1/sagas/{saga.saga_id}/cancel")

        assert response.status_code == 200
        result = SagaCancellationResponse.model_validate(response.json())
        assert result.saga_id == saga.saga_id
        assert isinstance(result.success, bool)
        assert result.message is not None

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_saga(
            self, test_user: AsyncClient
    ) -> None:
        """Cancel nonexistent saga returns 404."""
        response = await test_user.post(
            "/api/v1/sagas/nonexistent-saga-id/cancel"
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_other_users_saga_forbidden(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            long_running_execution_request: ExecutionRequest,
    ) -> None:
        """Cannot cancel another user's saga."""
        exec_response = await test_user.post(
            "/api/v1/execute", json=long_running_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution = ExecutionResponse.model_validate(exec_response.json())
        saga = await wait_for_saga(test_user, execution.execution_id)

        response = await another_user.post(f"/api/v1/sagas/{saga.saga_id}/cancel")

        assert response.status_code == 403


class TestSagaIsolation:
    """Tests for saga access isolation between users."""

    @pytest.mark.asyncio
    async def test_user_cannot_see_other_users_sagas(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            created_execution: ExecutionResponse,
    ) -> None:
        """User's saga list does not include other users' sagas."""
        saga = await wait_for_saga(test_user, created_execution.execution_id)

        response = await another_user.get("/api/v1/sagas/")
        assert response.status_code == 200

        result = SagaListResponse.model_validate(response.json())
        saga_ids = [s.saga_id for s in result.sagas]

        assert saga.saga_id not in saga_ids
