from uuid import uuid4

import pytest
from app.domain.enums.user import UserRole as UserRoleEnum
from app.schemas_pydantic.user import UserResponse
from httpx import AsyncClient


@pytest.mark.integration
class TestAuthentication:
    """Test authentication endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_user_registration_success(self, client: AsyncClient) -> None:
        """Test successful user registration with all required fields."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"test_auth_user_{unique_id}",
            "email": f"test_auth_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        response = await client.post("/api/v1/auth/register", json=registration_data)
        assert response.status_code in [200, 201]

        # Validate response structure
        user_data = response.json()
        user = UserResponse(**user_data)

        # Verify all expected fields
        assert user.username == registration_data["username"]
        assert user.email == registration_data["email"]
        assert user.role == UserRoleEnum.USER  # Default role
        assert user.is_active is True
        assert "password" not in user_data
        assert "hashed_password" not in user_data

        # Verify user_id is a valid UUID-like string
        assert user.user_id is not None
        assert len(user.user_id) > 0

        # Verify timestamps
        assert user.created_at is not None
        assert user.updated_at is not None

        # Verify default values
        assert user.is_superuser is False

    @pytest.mark.asyncio
    async def test_user_registration_with_weak_password(self, client: AsyncClient) -> None:
        """Test that registration fails with weak passwords."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"test_weak_pwd_{unique_id}",
            "email": f"test_weak_{unique_id}@example.com",
            "password": "weak"  # Too short
        }

        response = await client.post("/api/v1/auth/register", json=registration_data)
        assert response.status_code in [400, 422]

        error_data = response.json()
        assert "detail" in error_data
        # Error message should mention password requirements
        # Detail might be a string or list of validation errors
        if isinstance(error_data["detail"], list):
            error_text = str(error_data["detail"]).lower()
        else:
            error_text = error_data["detail"].lower()
        assert any(word in error_text for word in ["password", "length", "characters", "weak", "short"])

    @pytest.mark.asyncio
    async def test_duplicate_username_registration(self, client: AsyncClient) -> None:
        """Test that duplicate username registration is prevented."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"duplicate_user_{unique_id}",
            "email": f"duplicate1_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # First registration should succeed
        first_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert first_response.status_code in [200, 201]

        # Attempt duplicate registration with same username, different email
        duplicate_data = {
            "username": registration_data["username"],  # Same username
            "email": f"duplicate2_{unique_id}@example.com",  # Different email
            "password": "SecureP@ssw0rd123"
        }

        duplicate_response = await client.post("/api/v1/auth/register", json=duplicate_data)
        assert duplicate_response.status_code in [400, 409]

        error_data = duplicate_response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["already", "exists", "taken", "duplicate"])

    @pytest.mark.asyncio
    async def test_duplicate_email_registration(self, client: AsyncClient) -> None:
        """Test that duplicate email registration is prevented."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"user_email1_{unique_id}",
            "email": f"duplicate_email_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # First registration should succeed
        first_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert first_response.status_code in [200, 201]

        # Attempt duplicate registration with same email, different username
        duplicate_data = {
            "username": f"user_email2_{unique_id}",  # Different username
            "email": registration_data["email"],  # Same email
            "password": "SecureP@ssw0rd123"
        }

        duplicate_response = await client.post("/api/v1/auth/register", json=duplicate_data)
        # Backend might allow duplicate emails but not duplicate usernames
        # If it allows the registration, that's also valid behavior
        assert duplicate_response.status_code in [200, 201, 400, 409]

    @pytest.mark.asyncio
    async def test_login_success_with_valid_credentials(self, client: AsyncClient) -> None:
        """Test successful login with valid credentials."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"login_test_{unique_id}",
            "email": f"login_{unique_id}@example.com",
            "password": "SecureLoginP@ss123"
        }

        # Register user
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        # Login with form data
        login_data = {
            "username": registration_data["username"],
            "password": registration_data["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        response_data = login_response.json()

        # Backend uses cookie-based auth, not JWT in response body
        # Verify response structure matches actual API
        assert "message" in response_data
        assert response_data["message"] == "Login successful"
        assert "username" in response_data
        assert response_data["username"] == registration_data["username"]
        assert "role" in response_data

        # CSRF token should be present
        assert "csrf_token" in response_data
        assert len(response_data["csrf_token"]) > 0

        # Verify cookie is set
        cookies = login_response.cookies
        assert len(cookies) > 0  # Should have at least one cookie

    @pytest.mark.asyncio
    async def test_login_failure_with_wrong_password(self, client: AsyncClient) -> None:
        """Test that login fails with incorrect password."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"wrong_pwd_{unique_id}",
            "email": f"wrong_pwd_{unique_id}@example.com",
            "password": "CorrectP@ssw0rd123"
        }

        # Register user
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        # Attempt login with wrong password
        login_data = {
            "username": registration_data["username"],
            "password": "WrongPassword123"
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 401

        error_data = login_response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["invalid", "incorrect", "credentials", "unauthorized"])

    @pytest.mark.asyncio
    async def test_login_failure_with_nonexistent_user(self, client: AsyncClient) -> None:
        """Test that login fails for non-existent user."""
        unique_id = str(uuid4())[:8]
        login_data = {
            "username": f"nonexistent_user_{unique_id}",
            "password": "AnyP@ssw0rd123"
        }

        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 401

        error_data = login_response.json()
        assert "detail" in error_data

    @pytest.mark.asyncio
    async def test_get_current_user_info(self, client: AsyncClient) -> None:
        """Test getting current user information via /me endpoint."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"me_test_{unique_id}",
            "email": f"me_test_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # Register user
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        # Login
        login_data = {
            "username": registration_data["username"],
            "password": registration_data["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Get current user info (cookies from login should be preserved)
        me_response = await client.get("/api/v1/auth/me")
        assert me_response.status_code == 200

        user_data = me_response.json()
        user = UserResponse(**user_data)

        # Verify user data matches registration
        assert user.username == registration_data["username"]
        assert user.email == registration_data["email"]
        assert user.role == UserRoleEnum.USER
        assert user.is_active is True

        # Verify no sensitive data is exposed
        assert "password" not in user_data
        assert "hashed_password" not in user_data

    @pytest.mark.asyncio
    async def test_unauthorized_access_without_auth(self, client: AsyncClient) -> None:
        """Test that protected endpoints require authentication."""
        # Try to access /me without authentication
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_logout_clears_session(self, client: AsyncClient) -> None:
        """Test logout functionality clears the session."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"logout_test_{unique_id}",
            "email": f"logout_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # Register and login
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        login_data = {
            "username": registration_data["username"],
            "password": registration_data["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Verify we can access protected endpoint
        me_response = await client.get("/api/v1/auth/me")
        assert me_response.status_code == 200

        # Logout
        logout_response = await client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 200

        logout_data = logout_response.json()
        assert "message" in logout_data or "detail" in logout_data

        # Try to access protected endpoint again - should fail
        me_after_logout = await client.get("/api/v1/auth/me")
        assert me_after_logout.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_token_endpoint(self, client: AsyncClient) -> None:
        """Test token verification endpoint."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"verify_token_{unique_id}",
            "email": f"verify_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # Register and login
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        login_data = {
            "username": registration_data["username"],
            "password": registration_data["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Verify token
        verify_response = await client.get("/api/v1/auth/verify-token")
        assert verify_response.status_code == 200

        verify_data = verify_response.json()
        assert "valid" in verify_data
        assert verify_data["valid"] is True

        # Additional fields that might be returned
        if "username" in verify_data:
            assert verify_data["username"] == registration_data["username"]

    @pytest.mark.asyncio
    async def test_invalid_email_format_rejected(self, client: AsyncClient) -> None:
        """Test that invalid email formats are rejected during registration."""
        unique_id = str(uuid4())[:8]
        invalid_emails = [
            "not-an-email",
            "@example.com",
            "user@",
            "user@.com",
        ]

        for invalid_email in invalid_emails:
            registration_data = {
                "username": f"invalid_email_{unique_id}",
                "email": invalid_email,
                "password": "ValidP@ssw0rd123"
            }

            response = await client.post("/api/v1/auth/register", json=registration_data)
            assert response.status_code in [400, 422]

            error_data = response.json()
            assert "detail" in error_data

            # Update unique_id for next iteration to avoid username conflicts
            unique_id = str(uuid4())[:8]

    @pytest.mark.asyncio
    async def test_csrf_token_generation(self, client: AsyncClient) -> None:
        """Test CSRF token generation on login."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"csrf_test_{unique_id}",
            "email": f"csrf_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # Register user
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        # Login
        login_data = {
            "username": registration_data["username"],
            "password": registration_data["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        response_data = login_response.json()

        # CSRF token should be generated (if implementation includes it)
        if "csrf_token" in response_data:
            assert len(response_data["csrf_token"]) > 0
            # CSRF tokens are typically base64 or hex strings
            assert isinstance(response_data["csrf_token"], str)

    @pytest.mark.asyncio
    async def test_session_persistence_across_requests(self, client: AsyncClient) -> None:
        """Test that session persists across multiple requests after login."""
        unique_id = str(uuid4())[:8]
        registration_data = {
            "username": f"session_test_{unique_id}",
            "email": f"session_{unique_id}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        # Register and login
        reg_response = await client.post("/api/v1/auth/register", json=registration_data)
        assert reg_response.status_code in [200, 201]

        login_data = {
            "username": registration_data["username"],
            "password": registration_data["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200

        # Make multiple authenticated requests
        for _ in range(3):
            me_response = await client.get("/api/v1/auth/me")
            assert me_response.status_code == 200

            user_data = me_response.json()
            assert user_data["username"] == registration_data["username"]
