import uuid

import pytest
from httpx2 import AsyncClient
from pydantic import SecretStr

from app.domain.enums import UserRole
from app.schemas_pydantic.user import (
    LoginResponse,
    MessageResponse,
    UserCreate,
    UserResponse,
)

pytestmark = [pytest.mark.e2e]


class TestAuthLogin:
    """Tests for POST /api/v1/auth/login."""

    async def test_login_success(self, client: AsyncClient, new_user_request: UserCreate) -> None:
        """Login with valid credentials returns LoginResponse."""
        await client.post(
            "/api/v1/auth/register",
            json=new_user_request.model_dump(mode="json") | {"password": new_user_request.password.get_secret_value()},
        )

        response = await client.post(
            "/api/v1/auth/login",
            data={"username": new_user_request.username, "password": new_user_request.password.get_secret_value()},
        )

        assert response.status_code == 200
        result = LoginResponse.model_validate(response.json())

        assert result.username == new_user_request.username
        assert result.role in [UserRole.USER, UserRole.ADMIN]
        assert result.csrf_token and len(result.csrf_token) > 0
        assert result.message == "Login successful"
        assert "access_token" in response.cookies
        assert "csrf_token" in response.cookies

    async def test_login_invalid_password(self, client: AsyncClient, new_user_request: UserCreate) -> None:
        """Invalid password returns 401 with error detail."""
        await client.post(
            "/api/v1/auth/register",
            json=new_user_request.model_dump(mode="json") | {"password": new_user_request.password.get_secret_value()},
        )

        # Login with wrong password
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": new_user_request.username, "password": "WrongPass123!"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    async def test_login_nonexistent_user(self, client: AsyncClient) -> None:
        """Nonexistent user returns 401."""
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": f"nobody_{uuid.uuid4().hex}", "password": "whatever"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid credentials"

    async def test_login_empty_credentials(self, client: AsyncClient) -> None:
        """Empty username/password returns 422 validation error."""
        response = await client.post("/api/v1/auth/login", data={})

        assert response.status_code == 422

    async def test_login_deactivated_account(
        self, client: AsyncClient, test_admin: AsyncClient, new_user_request: UserCreate
    ) -> None:
        """Deactivated account returns 403 even with the right password."""
        created = await client.post(
            "/api/v1/auth/register",
            json=new_user_request.model_dump(mode="json") | {"password": new_user_request.password.get_secret_value()},
        )
        user_id = created.json()["user_id"]
        deactivated = await test_admin.put(f"/api/v1/admin/users/{user_id}", json={"is_active": False})
        assert deactivated.status_code == 200

        response = await client.post(
            "/api/v1/auth/login",
            data={"username": new_user_request.username, "password": new_user_request.password.get_secret_value()},
        )

        assert response.status_code == 403
        assert response.json() == {
            "detail": f"Account '{new_user_request.username}' is deactivated",
            "status": 403,
        }


class TestAuthRegister:
    """Tests for POST /api/v1/auth/register."""

    async def test_register_success(self, client: AsyncClient, new_user_request: UserCreate) -> None:
        """Register new user returns UserResponse with all fields."""
        response = await client.post(
            "/api/v1/auth/register",
            json=new_user_request.model_dump(mode="json") | {"password": new_user_request.password.get_secret_value()},
        )

        assert response.status_code == 200
        result = UserResponse.model_validate(response.json())

        # Validate UUID format
        uuid.UUID(result.user_id)
        assert result.username == new_user_request.username
        assert result.email == new_user_request.email
        assert result.role == UserRole.USER
        assert result.is_superuser is False

    async def test_register_duplicate_username(self, client: AsyncClient, new_user_request: UserCreate) -> None:
        """Duplicate username returns 409."""
        await client.post(
            "/api/v1/auth/register",
            json=new_user_request.model_dump(mode="json") | {"password": new_user_request.password.get_secret_value()},
        )

        # Try same username with different email
        second_request = UserCreate(
            username=new_user_request.username,
            email=f"other_{uuid.uuid4().hex[:8]}@test.com",
            password=SecretStr("Pass123!"),
            role=UserRole.USER,
        )
        response = await client.post(
            "/api/v1/auth/register",
            json=second_request.model_dump(mode="json") | {"password": second_request.password.get_secret_value()},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Username already registered"

    async def test_register_duplicate_email(self, client: AsyncClient, new_user_request: UserCreate) -> None:
        """Duplicate email returns 409."""
        await client.post(
            "/api/v1/auth/register",
            json=new_user_request.model_dump(mode="json") | {"password": new_user_request.password.get_secret_value()},
        )

        # Try same email with different username
        second_request = UserCreate(
            username=f"other_{uuid.uuid4().hex[:8]}",
            email=new_user_request.email,
            password=SecretStr("Pass123!"),
            role=UserRole.USER,
        )
        response = await client.post(
            "/api/v1/auth/register",
            json=second_request.model_dump(mode="json") | {"password": second_request.password.get_secret_value()},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Email already registered"

    async def test_register_invalid_email_format(self, client: AsyncClient) -> None:
        """Invalid email format returns 422."""
        uid = uuid.uuid4().hex[:8]

        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": f"user_{uid}",
                "email": "not-an-email",
                "password": "Pass123!",
                "role": "user",
            },
        )

        assert response.status_code == 422

    async def test_register_password_too_short(self, client: AsyncClient) -> None:
        """Password under the schema minimum returns 422 with field errors."""
        uid = uuid.uuid4().hex[:8]

        response = await client.post(
            "/api/v1/auth/register",
            json={"username": f"user_{uid}", "email": f"user_{uid}@test.com", "password": "short"},
        )

        assert response.status_code == 422
        assert response.json() == {
            "status": 422,
            "detail": "password: Value should have at least 8 items after validation, not 5",
        }


class TestAuthMe:
    """Tests for GET /api/v1/auth/me."""

    async def test_get_profile_authenticated(self, test_user: AsyncClient) -> None:
        """Authenticated user gets their profile."""
        response = await test_user.get("/api/v1/auth/me")

        assert response.status_code == 200
        result = UserResponse.model_validate(response.json())

        assert result.user_id
        assert result.username
        assert result.email
        assert result.role in [UserRole.USER, UserRole.ADMIN]
        assert response.headers.get("Cache-Control") == "no-store"

    async def test_get_profile_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401


class TestAuthLogout:
    """Tests for POST /api/v1/auth/logout."""

    async def test_logout_success(self, test_user: AsyncClient) -> None:
        """Logout returns success message and clears cookies."""
        response = await test_user.post("/api/v1/auth/logout")

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert result.message == "Logout successful"

    async def test_logout_unauthenticated(self, client: AsyncClient) -> None:
        """Logout without auth still succeeds (idempotent)."""
        response = await client.post("/api/v1/auth/logout")

        # Logout is typically idempotent - should succeed even without auth
        assert response.status_code == 200

    async def test_logout_without_csrf_header(self, test_user: AsyncClient) -> None:
        """Logged-in logout without the CSRF header returns 403."""
        del test_user.headers["X-CSRF-Token"]

        response = await test_user.post("/api/v1/auth/logout")

        assert response.status_code == 403
        assert response.json() == {"detail": "CSRF validation failed", "status": 403}
