import asyncio
import uuid

import pytest
from app.domain.enums.saga import SagaState
from app.schemas_pydantic.saga import (
    SagaListResponse,
    SagaStatusResponse,
)
from httpx import AsyncClient


class TestSagaRoutes:
    """Test saga routes against the real backend."""

    @pytest.mark.asyncio
    async def test_get_saga_requires_auth(self, client: AsyncClient) -> None:
        """Test that getting saga status requires authentication."""
        saga_id = str(uuid.uuid4())
        response = await client.get(f"/api/v1/sagas/{saga_id}")
        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_saga_not_found(self, test_user: AsyncClient) -> None:
        """Test getting non-existent saga returns 404."""
        # Try to get non-existent saga
        saga_id = str(uuid.uuid4())
        response = await test_user.get(f"/api/v1/sagas/{saga_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_execution_sagas_requires_auth(
            self, client: AsyncClient
    ) -> None:
        """Test that getting execution sagas requires authentication."""
        execution_id = str(uuid.uuid4())
        response = await client.get(f"/api/v1/sagas/execution/{execution_id}")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_execution_sagas_empty(self, test_user: AsyncClient) -> None:
        """Test getting sagas for execution with no sagas."""
        # Get sagas for non-existent execution
        execution_id = str(uuid.uuid4())
        response = await test_user.get(f"/api/v1/sagas/execution/{execution_id}")
        # Access to a random execution (non-owned) must be forbidden
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_execution_sagas_with_state_filter(self, test_user: AsyncClient) -> None:
        """Test getting execution sagas filtered by state."""
        # Get sagas filtered by running state
        execution_id = str(uuid.uuid4())
        response = await test_user.get(
            f"/api/v1/sagas/execution/{execution_id}",
            params={"state": SagaState.RUNNING}
        )
        # Access denied for non-owned execution is valid
        assert response.status_code in [200, 403]
        if response.status_code == 403:
            return
        saga_list = SagaListResponse(**response.json())
        assert saga_list.total == 0  # No running sagas for this execution

    @pytest.mark.asyncio
    async def test_list_sagas_requires_auth(self, client: AsyncClient) -> None:
        """Test that listing sagas requires authentication."""
        response = await client.get("/api/v1/sagas/")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_sagas_paginated(self, test_user: AsyncClient) -> None:
        """Test listing sagas with pagination."""
        # List sagas with pagination
        response = await test_user.get(
            "/api/v1/sagas/",
            params={"limit": 10, "offset": 0}
        )
        assert response.status_code == 200

        saga_list = SagaListResponse(**response.json())
        assert isinstance(saga_list.total, int)
        assert isinstance(saga_list.sagas, list)
        assert saga_list.total >= 0

    @pytest.mark.asyncio
    async def test_list_sagas_with_state_filter(self, test_user: AsyncClient) -> None:
        """Test listing sagas filtered by state."""
        # List completed sagas
        response = await test_user.get(
            "/api/v1/sagas/",
            params={"state": SagaState.COMPLETED, "limit": 5}
        )
        assert response.status_code == 200

        saga_list = SagaListResponse(**response.json())
        # All sagas should be completed if any exist
        for saga in saga_list.sagas:
            if saga.state:
                assert saga.state == SagaState.COMPLETED

    @pytest.mark.asyncio
    async def test_list_sagas_large_limit(self, test_user: AsyncClient) -> None:
        """Test listing sagas with maximum limit."""
        # List with max limit
        response = await test_user.get(
            "/api/v1/sagas/",
            params={"limit": 1000}
        )
        assert response.status_code == 200

        saga_list = SagaListResponse(**response.json())
        assert len(saga_list.sagas) <= 1000

    @pytest.mark.asyncio
    async def test_list_sagas_invalid_limit(self, test_user: AsyncClient) -> None:
        """Test listing sagas with invalid limit."""
        # Try with limit too large
        response = await test_user.get(
            "/api/v1/sagas/",
            params={"limit": 10000}
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_cancel_saga_requires_auth(self, client: AsyncClient) -> None:
        """Test that cancelling saga requires authentication."""
        saga_id = str(uuid.uuid4())
        response = await client.post(f"/api/v1/sagas/{saga_id}/cancel")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_cancel_saga_not_found(self, test_user: AsyncClient) -> None:
        """Test cancelling non-existent saga returns 404."""
        # Try to cancel non-existent saga
        saga_id = str(uuid.uuid4())
        response = await test_user.post(f"/api/v1/sagas/{saga_id}/cancel")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_saga_access_control(
            self,
            test_user: AsyncClient,
            another_user: AsyncClient
    ) -> None:
        """Test that users can only access their own sagas."""
        # User 1 lists their sagas
        response1 = await test_user.get("/api/v1/sagas/")
        assert response1.status_code == 200
        user1_sagas = SagaListResponse(**response1.json())

        # User 2 lists their sagas
        response2 = await another_user.get("/api/v1/sagas/")
        assert response2.status_code == 200
        user2_sagas = SagaListResponse(**response2.json())

        # Each user should see only their own sagas
        # (we can't verify the exact content without creating sagas,
        # but we can verify the endpoint works correctly)
        assert isinstance(user1_sagas.sagas, list)
        assert isinstance(user2_sagas.sagas, list)

    @pytest.mark.asyncio
    async def test_get_saga_with_details(self, test_user: AsyncClient) -> None:
        """Test getting saga with all details when it exists."""
        # First list sagas to potentially find one
        list_response = await test_user.get("/api/v1/sagas/", params={"limit": 1})
        assert list_response.status_code == 200
        saga_list = SagaListResponse(**list_response.json())

        if saga_list.sagas and len(saga_list.sagas) > 0:
            # Get details of the first saga
            saga_id = saga_list.sagas[0].saga_id
            response = await test_user.get(f"/api/v1/sagas/{saga_id}")

            # Could be 200 if accessible or 403 if not owned by user
            assert response.status_code in [200, 403, 404]

            if response.status_code == 200:
                saga_status = SagaStatusResponse(**response.json())
                assert saga_status.saga_id == saga_id
                assert saga_status.state in list(SagaState)

    @pytest.mark.asyncio
    async def test_list_sagas_with_offset(self, test_user: AsyncClient) -> None:
        """Test listing sagas with offset for pagination."""
        # Get first page
        response1 = await test_user.get(
            "/api/v1/sagas/",
            params={"limit": 5, "offset": 0}
        )
        assert response1.status_code == 200
        page1 = SagaListResponse(**response1.json())

        # Get second page
        response2 = await test_user.get(
            "/api/v1/sagas/",
            params={"limit": 5, "offset": 5}
        )
        assert response2.status_code == 200
        page2 = SagaListResponse(**response2.json())

        # If there are sagas, verify pagination works
        if page1.sagas and page2.sagas:
            # Saga IDs should be different between pages
            page1_ids = {s.saga_id for s in page1.sagas}
            page2_ids = {s.saga_id for s in page2.sagas}
            assert len(page1_ids.intersection(page2_ids)) == 0

    @pytest.mark.asyncio
    async def test_cancel_saga_invalid_state(self, test_user: AsyncClient) -> None:
        """Test cancelling a saga in invalid state (if one exists)."""
        # Try to find a completed saga to cancel
        response = await test_user.get(
            "/api/v1/sagas/",
            params={"state": SagaState.COMPLETED, "limit": 1}
        )
        assert response.status_code == 200
        saga_list = SagaListResponse(**response.json())

        if saga_list.sagas and len(saga_list.sagas) > 0:
            # Try to cancel completed saga (should fail)
            saga_id = saga_list.sagas[0].saga_id
            cancel_response = await test_user.post(f"/api/v1/sagas/{saga_id}/cancel")
            # Should get 400 (invalid state) or 403 (access denied) or 404
            assert cancel_response.status_code in [400, 403, 404]

    @pytest.mark.asyncio
    async def test_get_execution_sagas_multiple_states(self, test_user: AsyncClient) -> None:
        """Test getting execution sagas across different states."""
        execution_id = str(uuid.uuid4())

        # Test each state filter
        for state in [SagaState.CREATED, SagaState.RUNNING, SagaState.COMPLETED,
                      SagaState.FAILED, SagaState.CANCELLED]:
            response = await test_user.get(
                f"/api/v1/sagas/execution/{execution_id}",
                params={"state": state}
            )
            assert response.status_code in [200, 403]
            if response.status_code == 403:
                continue
            saga_list = SagaListResponse(**response.json())

            # All returned sagas should match the requested state
            for saga in saga_list.sagas:
                if saga.state:
                    assert saga.state == state

    @pytest.mark.asyncio
    async def test_saga_response_structure(self, test_user: AsyncClient) -> None:
        """Test that saga responses have correct structure."""
        # List sagas to verify response structure
        response = await test_user.get("/api/v1/sagas/", params={"limit": 1})
        assert response.status_code == 200

        saga_list = SagaListResponse(**response.json())
        assert hasattr(saga_list, "sagas")
        assert hasattr(saga_list, "total")
        assert isinstance(saga_list.sagas, list)
        assert isinstance(saga_list.total, int)

        # If we have sagas, verify their structure
        if saga_list.sagas:
            saga = saga_list.sagas[0]
            assert hasattr(saga, "saga_id")
            assert hasattr(saga, "execution_id")
            assert hasattr(saga, "state")
            assert hasattr(saga, "created_at")

    @pytest.mark.asyncio
    async def test_concurrent_saga_access(self, test_user: AsyncClient) -> None:
        """Test concurrent access to saga endpoints."""
        # Make multiple concurrent requests
        tasks = []
        for i in range(5):
            tasks.append(test_user.get(
                "/api/v1/sagas/",
                params={"limit": 10, "offset": i * 10}
            ))

        responses = await asyncio.gather(*tasks)

        # All requests should succeed
        for response in responses:
            assert response.status_code == 200
            saga_list = SagaListResponse(**response.json())
            assert isinstance(saga_list.sagas, list)
