import httpx
import pytest
from app.domain.exceptions import DomainError
from fastapi import FastAPI

pytestmark = pytest.mark.e2e


class TestExceptionHandlerRegistration:
    """Tests that exception handlers are properly registered."""

    def test_domain_error_handler_registered(self, app: FastAPI) -> None:
        """DomainError handler is registered on app."""
        assert DomainError in app.exception_handlers


class TestExceptionHandlerBehavior:
    """Tests for exception handler behavior via HTTP requests."""

    @pytest.mark.asyncio
    async def test_not_found_returns_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """Nonexistent execution returns 404."""
        response = await client.get(
            "/api/v1/executions/nonexistent-id-12345/result"
        )

        assert response.status_code == 404
        body = response.json()
        assert "detail" in body

    @pytest.mark.asyncio
    async def test_unauthorized_returns_401(
        self, client: httpx.AsyncClient
    ) -> None:
        """Invalid credentials return 401."""
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "nonexistent", "password": "wrongpass"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_forbidden_returns_403(
        self, test_user: httpx.AsyncClient
    ) -> None:
        """Accessing admin endpoint as user returns 403."""
        response = await test_user.get("/api/v1/admin/users")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_validation_error_format(
        self, test_user: httpx.AsyncClient
    ) -> None:
        """Validation errors return proper format."""
        # Send invalid data (empty script)
        response = await test_user.post(
            "/api/v1/execute",
            json={
                "script": "",  # Empty script should fail validation
                "lang": "python",
                "lang_version": "3.11",
            },
        )

        # Should get 422 for validation error
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_conflict_error_on_duplicate(
        self, client: httpx.AsyncClient
    ) -> None:
        """Duplicate registration returns 409."""
        # First registration
        import uuid

        unique_suffix = uuid.uuid4().hex[:8]
        user_data = {
            "username": f"duplicate_test_{unique_suffix}",
            "email": f"duplicate_{unique_suffix}@example.com",
            "password": "TestPass123!",
        }

        response1 = await client.post("/api/v1/auth/register", json=user_data)
        assert response1.status_code == 200

        # Second registration with same email
        response2 = await client.post("/api/v1/auth/register", json=user_data)
        # Should be 409 or 400 depending on implementation
        assert response2.status_code in (400, 409)
