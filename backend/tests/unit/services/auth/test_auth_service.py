import logging
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.domain.enums.user import UserRole
from app.domain.user import AdminAccessRequiredError, AuthenticationRequiredError
from app.services.auth_service import AuthService

pytestmark = pytest.mark.unit


class FakeUser:
    """Minimal user mock for testing."""

    def __init__(
        self,
        user_id: str = "user-123",
        username: str = "testuser",
        email: str = "test@example.com",
        role: UserRole = UserRole.USER,
        is_superuser: bool = False,
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.email = email
        self.role = role
        self.is_superuser = is_superuser
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class FakeRequest:
    """Minimal request mock for testing."""

    def __init__(self, cookies: dict[str, str] | None = None) -> None:
        self.cookies = cookies or {}


@pytest.fixture
def mock_user_repo() -> AsyncMock:
    """Mock user repository."""
    return AsyncMock()


@pytest.fixture
def mock_logger() -> MagicMock:
    """Mock logger."""
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def auth_service(mock_user_repo: AsyncMock, mock_logger: MagicMock) -> AuthService:
    """Create AuthService with mocked dependencies."""
    return AuthService(user_repo=mock_user_repo, logger=mock_logger)


class TestGetCurrentUser:
    """Tests for get_current_user method."""

    async def test_raises_when_no_token_cookie(
        self, auth_service: AuthService
    ) -> None:
        """Raises AuthenticationRequiredError when access_token cookie is missing."""
        request = FakeRequest(cookies={})

        with pytest.raises(AuthenticationRequiredError):
            await auth_service.get_current_user(request)  # type: ignore

    async def test_raises_when_token_empty(
        self, auth_service: AuthService
    ) -> None:
        """Raises AuthenticationRequiredError when token is empty string."""
        request = FakeRequest(cookies={"access_token": ""})

        with pytest.raises(AuthenticationRequiredError):
            await auth_service.get_current_user(request)  # type: ignore

    @pytest.mark.parametrize(
        "role,is_superuser",
        [
            (UserRole.USER, False),
            (UserRole.ADMIN, False),
            (UserRole.ADMIN, True),
        ],
        ids=["regular-user", "admin-not-superuser", "admin-superuser"],
    )
    async def test_returns_user_response_for_valid_token(
        self,
        auth_service: AuthService,
        role: UserRole,
        is_superuser: bool,
    ) -> None:
        """Returns UserResponse with correct fields for valid tokens."""
        fake_user = FakeUser(
            user_id="uid-456",
            username="validuser",
            email="valid@example.com",
            role=role,
            is_superuser=is_superuser,
        )

        with patch("app.services.auth_service.security_service") as mock_security:
            mock_security.get_current_user = AsyncMock(return_value=fake_user)
            request = FakeRequest(cookies={"access_token": "valid-jwt-token"})

            result = await auth_service.get_current_user(request)  # type: ignore

            assert result.user_id == "uid-456"
            assert result.username == "validuser"
            assert result.email == "valid@example.com"
            assert result.role == role
            assert result.is_superuser == is_superuser
            mock_security.get_current_user.assert_called_once_with(
                "valid-jwt-token", auth_service.user_repo
            )

    async def test_propagates_security_service_exception(
        self, auth_service: AuthService
    ) -> None:
        """Propagates exceptions from security_service.get_current_user."""
        with patch("app.services.auth_service.security_service") as mock_security:
            mock_security.get_current_user = AsyncMock(
                side_effect=AuthenticationRequiredError("Invalid token")
            )
            request = FakeRequest(cookies={"access_token": "invalid-token"})

            with pytest.raises(AuthenticationRequiredError):
                await auth_service.get_current_user(request)  # type: ignore


class TestGetAdmin:
    """Tests for get_admin method."""

    async def test_returns_admin_user(
        self, auth_service: AuthService
    ) -> None:
        """Returns user when they have ADMIN role."""
        fake_admin = FakeUser(
            user_id="admin-789",
            username="adminuser",
            email="admin@example.com",
            role=UserRole.ADMIN,
        )

        with patch("app.services.auth_service.security_service") as mock_security:
            mock_security.get_current_user = AsyncMock(return_value=fake_admin)
            request = FakeRequest(cookies={"access_token": "admin-token"})

            result = await auth_service.get_admin(request)  # type: ignore

            assert result.user_id == "admin-789"
            assert result.role == UserRole.ADMIN

    @pytest.mark.parametrize(
        "role",
        [UserRole.USER],
        ids=["regular-user"],
    )
    async def test_raises_for_non_admin_role(
        self,
        auth_service: AuthService,
        mock_logger: MagicMock,
        role: UserRole,
    ) -> None:
        """Raises AdminAccessRequiredError for non-admin roles."""
        fake_user = FakeUser(
            user_id="user-123",
            username="normaluser",
            email="user@example.com",
            role=role,
        )

        with patch("app.services.auth_service.security_service") as mock_security:
            mock_security.get_current_user = AsyncMock(return_value=fake_user)
            request = FakeRequest(cookies={"access_token": "user-token"})

            with pytest.raises(AdminAccessRequiredError) as exc_info:
                await auth_service.get_admin(request)  # type: ignore

            assert "normaluser" in str(exc_info.value)
            mock_logger.warning.assert_called_once()
            assert "normaluser" in mock_logger.warning.call_args[0][0]

    async def test_propagates_auth_error_from_get_current_user(
        self, auth_service: AuthService
    ) -> None:
        """Propagates AuthenticationRequiredError from get_current_user."""
        request = FakeRequest(cookies={})

        with pytest.raises(AuthenticationRequiredError):
            await auth_service.get_admin(request)  # type: ignore


class TestAuthServiceEdgeCases:
    """Edge case tests for AuthService."""

    async def test_handles_none_in_cookies(
        self, auth_service: AuthService
    ) -> None:
        """Handles request.cookies returning None-like values gracefully."""
        request = MagicMock()
        request.cookies.get.return_value = None

        with pytest.raises(AuthenticationRequiredError):
            await auth_service.get_current_user(request)

    async def test_user_response_preserves_timestamps(
        self, auth_service: AuthService
    ) -> None:
        """UserResponse includes created_at and updated_at from domain user."""
        created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2024, 6, 15, 18, 30, 0, tzinfo=timezone.utc)
        fake_user = FakeUser()
        fake_user.created_at = created
        fake_user.updated_at = updated

        with patch("app.services.auth_service.security_service") as mock_security:
            mock_security.get_current_user = AsyncMock(return_value=fake_user)
            request = FakeRequest(cookies={"access_token": "token"})

            result = await auth_service.get_current_user(request)  # type: ignore

            assert result.created_at == created
            assert result.updated_at == updated
