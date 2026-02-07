import pytest
from app.domain.enums.saga import SagaState
from app.schemas_pydantic.execution import ExecutionRequest, ExecutionResponse
from app.schemas_pydantic.saga import (
    SagaCancellationResponse,
    SagaListResponse,
    SagaStatusResponse,
)
from httpx import AsyncClient

from tests.e2e.conftest import EventWaiter

pytestmark = [pytest.mark.e2e, pytest.mark.kafka]


class TestGetSagaStatus:
    """Tests for GET /api/v1/sagas/{saga_id}."""

    @pytest.mark.asyncio
    async def test_get_saga_status(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """Get saga status by ID returns valid response."""
        execution, saga = execution_with_saga

        response = await test_user.get(f"/api/v1/sagas/{saga.saga_id}")

        assert response.status_code == 200
        result = SagaStatusResponse.model_validate(response.json())
        assert result.saga_id == saga.saga_id
        assert result.execution_id == execution.execution_id
        assert result.state in {SagaState.CREATED, SagaState.RUNNING}
        assert result.saga_name
        assert result.retry_count >= 0
        assert result.error_message is None
        assert result.completed_steps is not None

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
            execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse],
    ) -> None:
        """Cannot access another user's saga."""
        _, saga = execution_with_saga

        response = await another_user.get(f"/api/v1/sagas/{saga.saga_id}")

        assert response.status_code == 403


class TestGetExecutionSagas:
    """Tests for GET /api/v1/sagas/execution/{execution_id}."""

    @pytest.mark.asyncio
    async def test_get_execution_sagas(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """Get sagas for a specific execution."""
        execution, saga = execution_with_saga

        response = await test_user.get(
            f"/api/v1/sagas/execution/{execution.execution_id}"
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert result.total == 1
        assert len(result.sagas) == 1
        assert isinstance(result.has_more, bool)

        saga_ids = [s.saga_id for s in result.sagas]
        assert saga.saga_id in saga_ids

    @pytest.mark.asyncio
    async def test_get_execution_sagas_with_pagination(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """Pagination works for execution sagas."""
        execution, _ = execution_with_saga

        response = await test_user.get(
            f"/api/v1/sagas/execution/{execution.execution_id}",
            params={"limit": 5, "skip": 0},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())
        assert result.limit == 5
        assert result.skip == 0
        assert len(result.sagas) <= 5

    @pytest.mark.asyncio
    async def test_get_execution_sagas_with_state_filter(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """Filter sagas by state."""
        execution, saga = execution_with_saga

        response = await test_user.get(
            f"/api/v1/sagas/execution/{execution.execution_id}",
            params={"state": saga.state.value},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())
        assert len(result.sagas) == 1
        for s in result.sagas:
            assert s.state == saga.state


class TestListSagas:
    """Tests for GET /api/v1/sagas/."""

    @pytest.mark.asyncio
    async def test_list_sagas(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """List sagas for current user."""
        _, saga = execution_with_saga

        response = await test_user.get("/api/v1/sagas/")

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert result.total >= 1
        assert len(result.sagas) >= 1
        assert len(result.sagas) <= result.limit

        saga_ids = [s.saga_id for s in result.sagas]
        assert saga.saga_id in saga_ids

    @pytest.mark.asyncio
    async def test_list_sagas_with_state_filter(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """Filter sagas by state."""
        _, saga = execution_with_saga

        response = await test_user.get(
            "/api/v1/sagas/",
            params={"state": saga.state.value},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert len(result.sagas) >= 1
        for s in result.sagas:
            assert s.state == saga.state

    @pytest.mark.asyncio
    async def test_list_sagas_pagination(
            self, test_user: AsyncClient, execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse]
    ) -> None:
        """Pagination works for saga list."""
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
            event_waiter: EventWaiter,
            long_running_execution_request: ExecutionRequest,
    ) -> None:
        """Cancel a running saga."""
        exec_response = await test_user.post(
            "/api/v1/execute", json=long_running_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution = ExecutionResponse.model_validate(exec_response.json())
        await event_waiter.wait_for_saga_started(execution.execution_id)

        saga_resp = await test_user.get(f"/api/v1/sagas/execution/{execution.execution_id}")
        saga = SagaListResponse.model_validate(saga_resp.json()).sagas[0]

        response = await test_user.post(f"/api/v1/sagas/{saga.saga_id}/cancel")

        assert response.status_code == 200
        result = SagaCancellationResponse.model_validate(response.json())
        assert result.saga_id == saga.saga_id
        assert result.success is True
        assert result.message is not None

        # Verify saga state actually changed
        status_resp = await test_user.get(f"/api/v1/sagas/{saga.saga_id}")
        assert status_resp.status_code == 200
        updated_saga = SagaStatusResponse.model_validate(status_resp.json())
        assert updated_saga.state in {SagaState.CANCELLED, SagaState.COMPENSATING}

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
            event_waiter: EventWaiter,
            long_running_execution_request: ExecutionRequest,
    ) -> None:
        """Cannot cancel another user's saga."""
        exec_response = await test_user.post(
            "/api/v1/execute", json=long_running_execution_request.model_dump()
        )
        assert exec_response.status_code == 200

        execution = ExecutionResponse.model_validate(exec_response.json())
        await event_waiter.wait_for_saga_started(execution.execution_id)

        saga_resp = await test_user.get(f"/api/v1/sagas/execution/{execution.execution_id}")
        saga = SagaListResponse.model_validate(saga_resp.json()).sagas[0]

        response = await another_user.post(f"/api/v1/sagas/{saga.saga_id}/cancel")

        assert response.status_code == 403


class TestSagaIsolation:
    """Tests for saga access isolation between users."""

    @pytest.mark.asyncio
    async def test_user_cannot_see_other_users_sagas(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient,
            execution_with_saga: tuple[ExecutionResponse, SagaStatusResponse],
    ) -> None:
        """User's saga list does not include other users' sagas."""
        _, saga = execution_with_saga
        assert saga.saga_id

        # Positive proof: owner CAN see the saga
        owner_resp = await test_user.get("/api/v1/sagas/")
        assert owner_resp.status_code == 200
        owner_result = SagaListResponse.model_validate(owner_resp.json())
        assert saga.saga_id in [s.saga_id for s in owner_result.sagas]

        # Negative proof: another user CANNOT see it
        response = await another_user.get("/api/v1/sagas/")
        assert response.status_code == 200

        result = SagaListResponse.model_validate(response.json())
        assert saga.saga_id not in [s.saga_id for s in result.sagas]
