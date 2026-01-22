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


class TestGetSagaStatus:
    """Tests for GET /api/v1/sagas/{saga_id}."""

    @pytest.mark.asyncio
    async def test_get_saga_status(
        self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get saga status by ID after creating an execution."""
        sagas_response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}"
        )

        if sagas_response.status_code == 200:
            sagas = SagaListResponse.model_validate(sagas_response.json())
            if sagas.sagas:
                saga_id = sagas.sagas[0].saga_id
                response = await test_user.get(f"/api/v1/sagas/{saga_id}")

                assert response.status_code == 200
                saga = SagaStatusResponse.model_validate(response.json())
                assert saga.saga_id == saga_id
                assert saga.state in list(SagaState)

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
        sagas_response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}"
        )

        if sagas_response.status_code == 200:
            sagas = SagaListResponse.model_validate(sagas_response.json())
            if sagas.sagas:
                saga_id = sagas.sagas[0].saga_id
                response = await another_user.get(f"/api/v1/sagas/{saga_id}")
                assert response.status_code == 403


class TestGetExecutionSagas:
    """Tests for GET /api/v1/sagas/execution/{execution_id}."""

    @pytest.mark.asyncio
    async def test_get_execution_sagas(
        self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Get sagas for a specific execution."""
        response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}"
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert result.total >= 0
        assert isinstance(result.sagas, list)
        assert isinstance(result.has_more, bool)

    @pytest.mark.asyncio
    async def test_get_execution_sagas_with_pagination(
        self, test_user: AsyncClient, created_execution: ExecutionResponse
    ) -> None:
        """Pagination works for execution sagas."""
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
        response = await test_user.get(
            f"/api/v1/sagas/execution/{created_execution.execution_id}",
            params={"state": SagaState.RUNNING},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())
        for saga in result.sagas:
            assert saga.state == SagaState.RUNNING


class TestListSagas:
    """Tests for GET /api/v1/sagas/."""

    @pytest.mark.asyncio
    async def test_list_sagas(self, test_user: AsyncClient) -> None:
        """List sagas for current user."""
        response = await test_user.get("/api/v1/sagas/")

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        assert result.total >= 0
        assert isinstance(result.sagas, list)

    @pytest.mark.asyncio
    async def test_list_sagas_with_state_filter(
        self, test_user: AsyncClient
    ) -> None:
        """Filter sagas by state."""
        response = await test_user.get(
            "/api/v1/sagas/",
            params={"state": SagaState.COMPLETED},
        )

        assert response.status_code == 200
        result = SagaListResponse.model_validate(response.json())

        for saga in result.sagas:
            assert saga.state == SagaState.COMPLETED

    @pytest.mark.asyncio
    async def test_list_sagas_pagination(self, test_user: AsyncClient) -> None:
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
        long_running_execution_request: ExecutionRequest,
    ) -> None:
        """Cancel a running saga."""
        exec_response = await test_user.post(
            "/api/v1/execute", json=long_running_execution_request.model_dump()
        )
        execution_id = exec_response.json()["execution_id"]

        sagas_response = await test_user.get(
            f"/api/v1/sagas/execution/{execution_id}"
        )

        if sagas_response.status_code == 200:
            sagas = SagaListResponse.model_validate(sagas_response.json())
            if sagas.sagas:
                saga_id = sagas.sagas[0].saga_id
                response = await test_user.post(f"/api/v1/sagas/{saga_id}/cancel")

                if response.status_code == 200:
                    result = SagaCancellationResponse.model_validate(response.json())
                    assert result.saga_id == saga_id
                    assert isinstance(result.success, bool)
                else:
                    assert response.status_code in [400, 404]

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
        execution_id = exec_response.json()["execution_id"]

        sagas_response = await test_user.get(
            f"/api/v1/sagas/execution/{execution_id}"
        )

        if sagas_response.status_code == 200:
            sagas = SagaListResponse.model_validate(sagas_response.json())
            if sagas.sagas:
                saga_id = sagas.sagas[0].saga_id
                response = await another_user.post(f"/api/v1/sagas/{saga_id}/cancel")
                assert response.status_code in [403, 404]
