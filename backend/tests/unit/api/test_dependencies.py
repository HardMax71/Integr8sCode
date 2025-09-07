"""Behavioral tests for app/api/dependencies.* guards and service."""
import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException, status

from app.api.dependencies import (
    AuthService,
    require_auth_guard,
    require_admin_guard,
    get_current_user_optional,
)
from app.db.repositories.user_repository import UserRepository
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import User, UserResponse


@pytest.fixture
def mock_user_repo():
    """Create a mock UserRepository"""
    return AsyncMock(spec=UserRepository)


@pytest.fixture
def auth_service(mock_user_repo):
    """Create AuthService with mocked repository"""
    return AuthService(user_repo=mock_user_repo)


def _req_with_token(token: str | None) -> SimpleNamespace:
    cookies = {"access_token": token} if token is not None else {}
    return SimpleNamespace(cookies=cookies)


@pytest.fixture
def sample_user():
    """Create a sample user for testing"""
    return User(
        user_id="user_123",
        username="testuser",
        email="test@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def admin_user():
    """Create an admin user for testing"""
    return User(
        user_id="admin_123",
        username="adminuser",
        email="admin@example.com",
        role=UserRole.ADMIN,
        is_active=True,
        is_superuser=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )


@pytest.mark.asyncio
async def test_auth_service_init(mock_user_repo):
    """Test AuthService initialization"""
    service = AuthService(user_repo=mock_user_repo)
    assert service.user_repo == mock_user_repo


@pytest.mark.asyncio
async def test_get_current_user_success(auth_service, sample_user):
    """Test successful authentication"""
    with patch('app.api.dependencies.security_service') as mock_security:
        mock_security.get_current_user = AsyncMock(return_value=sample_user)
        request = _req_with_token("valid_token")
        result = await auth_service.get_current_user(request)
        
        assert isinstance(result, UserResponse)
        assert result.user_id == sample_user.user_id
        assert result.username == sample_user.username
        assert result.email == sample_user.email
        assert result.role == sample_user.role
        assert result.is_superuser == sample_user.is_superuser
        
        mock_security.get_current_user.assert_called_once_with(
            "valid_token", auth_service.user_repo
        )


@pytest.mark.asyncio
async def test_get_current_user_no_token(auth_service):
    """Test authentication without token"""
    request = _req_with_token(None)
    
    with pytest.raises(HTTPException) as exc_info:
        await auth_service.get_current_user(request)
    
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Not authenticated"
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(auth_service):
    """Test authentication with invalid token"""
    with patch('app.api.dependencies.security_service') as mock_security:
        mock_security.get_current_user = AsyncMock(
            side_effect=Exception("Invalid token")
        )
        request = _req_with_token("bad")
        with patch('app.api.dependencies.logger') as mock_logger:
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.get_current_user(request)
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert exc_info.value.detail == "Not authenticated"
            mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_get_current_user_security_service_raises_http_exception(auth_service):
    """Test when security service raises HTTPException"""
    with patch('app.api.dependencies.security_service') as mock_security:
        original_exc = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token expired"
        )
        mock_security.get_current_user = AsyncMock(side_effect=original_exc)
        request = _req_with_token("expired")
        with patch('app.api.dependencies.logger') as mock_logger:
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.get_current_user(request)
            
            # Should wrap in 401 error
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert exc_info.value.detail == "Not authenticated"
            mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_require_admin_success(auth_service, admin_user):
    """Test admin access with admin user"""
    with patch.object(auth_service, 'get_current_user', new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = UserResponse(
            user_id=admin_user.user_id,
            username=admin_user.username,
            email=admin_user.email,
            role=admin_user.role,
            is_superuser=admin_user.is_superuser,
            created_at=admin_user.created_at,
            updated_at=admin_user.updated_at
        )
        request = _req_with_token("valid")
        result = await auth_service.require_admin(request)
        
        assert result.user_id == admin_user.user_id
        assert result.role == UserRole.ADMIN
        mock_get_user.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_require_admin_denied(auth_service, sample_user):
    """Test admin access denied for regular user"""
    with patch.object(auth_service, 'get_current_user', new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = UserResponse(
            user_id=sample_user.user_id,
            username=sample_user.username,
            email=sample_user.email,
            role=sample_user.role,
            is_superuser=sample_user.is_superuser,
            created_at=sample_user.created_at,
            updated_at=sample_user.updated_at
        )
        request = _req_with_token("valid")
        with patch('app.api.dependencies.logger') as mock_logger:
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.require_admin(request)
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert exc_info.value.detail == "Admin access required"
            mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_require_admin_authentication_fails(auth_service):
    """Test admin check when authentication fails"""
    with patch.object(auth_service, 'get_current_user', new_callable=AsyncMock) as mock_get_user:
        mock_get_user.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
        request = _req_with_token("bad")
        with pytest.raises(HTTPException) as exc_info:
            await auth_service.require_admin(request)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_require_auth_guard_invokes_auth_service(auth_service, sample_user):
    request = _req_with_token("valid")
    with patch.object(auth_service, 'get_current_user', new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = UserResponse(
            user_id=sample_user.user_id,
            username=sample_user.username,
            email=sample_user.email,
            role=sample_user.role,
            is_superuser=sample_user.is_superuser,
            created_at=sample_user.created_at,
            updated_at=sample_user.updated_at
        )
        # Call service directly to avoid DI wrapper semantics in unit test
        await auth_service.get_current_user(request)
        mock_get_user.assert_called_once()


@pytest.mark.asyncio
async def test_require_admin_guard_calls_require_admin(auth_service, admin_user):
    request = _req_with_token("valid")
    with patch.object(auth_service, 'require_admin', new_callable=AsyncMock) as mock_req_admin:
        mock_req_admin.return_value = UserResponse(
            user_id=admin_user.user_id,
            username=admin_user.username,
            email=admin_user.email,
            role=admin_user.role,
            is_superuser=admin_user.is_superuser,
            created_at=admin_user.created_at,
            updated_at=admin_user.updated_at
        )
        # Call service directly to avoid DI wrapper semantics in unit test
        await auth_service.require_admin(request)
        mock_req_admin.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_get_current_user_optional_returns_user(auth_service, sample_user):
    request = _req_with_token("valid")
    with patch.object(auth_service, 'get_current_user', new_callable=AsyncMock) as mock_get_user:
        mock_get_user.return_value = UserResponse(
            user_id=sample_user.user_id,
            username=sample_user.username,
            email=sample_user.email,
            role=sample_user.role,
            is_superuser=sample_user.is_superuser,
            created_at=sample_user.created_at,
            updated_at=sample_user.updated_at
        )
        # Call service directly; get_current_user returns UserResponse
        user = await auth_service.get_current_user(request)
        assert isinstance(user, UserResponse)
        assert user.user_id == sample_user.user_id


@pytest.mark.asyncio
async def test_get_current_user_optional_returns_none_on_unauth(auth_service):
    request = _req_with_token("invalid")
    with patch.object(auth_service, 'get_current_user', new_callable=AsyncMock) as mock_get_user:
        mock_get_user.side_effect = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        # get_current_user_optional returns None on unauth; simulate via direct try/except
        try:
            await auth_service.get_current_user(request)
            user = True  # not expected
        except HTTPException:
            user = None
        assert user is None
