from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import jwt
import pytest
from app.core.security import (
    SecurityService,
    get_token_from_cookie,
    validate_csrf_token,
    security_service
)
from app.db.repositories.user_repository import get_user_repository
from app.schemas_pydantic.user import UserInDB
from fastapi import HTTPException


class TestSecurityService:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.service = SecurityService()

    def test_init(self) -> None:
        assert self.service.pwd_context is not None
        assert self.service.settings is not None

    def test_password_operations(self) -> None:
        plain_password = "testpass123"

        hashed = self.service.get_password_hash(plain_password)

        assert hashed is not None
        assert isinstance(hashed, str)
        assert hashed != plain_password
        assert hashed.startswith("$2b$")

        assert self.service.verify_password(plain_password, hashed) is True
        assert self.service.verify_password("wrongpass", hashed) is False

    def test_access_token_creation(self) -> None:
        data = {"sub": "testuser"}
        expires_delta = timedelta(minutes=30)

        token_with_expiry = self.service.create_access_token(data, expires_delta)
        token_default = self.service.create_access_token(data)

        for token in [token_with_expiry, token_default]:
            assert token is not None
            payload = jwt.decode(token, self.service.settings.SECRET_KEY, algorithms=[self.service.settings.ALGORITHM])
            assert payload["sub"] == "testuser"
            assert "exp" in payload

    @pytest.mark.asyncio
    async def test_get_current_user_with_real_user(self, db: AsyncGenerator) -> None:
        user_repo = get_user_repository(db)

        test_user = UserInDB(
            id="507f1f77bcf86cd799439011",
            username=f"testuser_{int(datetime.utcnow().timestamp())}",
            email="test@example.com",
            hashed_password=self.service.get_password_hash("testpass"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

        created_user = await user_repo.create_user(test_user)

        token = self.service.create_access_token({"sub": created_user.username})

        user = await self.service.get_current_user(token, user_repo)

        assert user.username == created_user.username
        assert user.email == created_user.email

    @pytest.mark.asyncio
    async def test_get_current_user_scenarios(self, db: AsyncGenerator) -> None:
        user_repo = get_user_repository(db)

        test_cases = [
            ("invalid.token.here", "Could not validate credentials"),
            (self.service.create_access_token({"sub": "nonexistent_user_12345"}), None),
            (jwt.encode({"exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
                        self.service.settings.SECRET_KEY,
                        algorithm=self.service.settings.ALGORITHM), None)
        ]

        for token, expected_detail in test_cases:
            with pytest.raises(HTTPException) as exc_info:
                await self.service.get_current_user(token, user_repo)

            assert exc_info.value.status_code == 401
            if expected_detail:
                assert expected_detail in exc_info.value.detail

    def test_csrf_token_operations(self) -> None:
        token1 = self.service.generate_csrf_token()
        token2 = self.service.generate_csrf_token()

        assert token1 is not None
        assert token2 is not None
        assert token1 != token2
        assert len(token1) > 0
        assert len(token2) > 0

        test_cases = [
            ("test-csrf-token", "test-csrf-token", True),
            ("test-csrf-token", "different-csrf-token", False),
            ("", "cookie-token", False),
            ("header-token", "", False)
        ]

        for header_token, cookie_token, expected in test_cases:
            result = self.service.validate_csrf_token(header_token, cookie_token)
            assert result is expected


class TestGetTokenFromCookie:

    def test_get_token_from_cookie_scenarios(self) -> None:
        test_cases = [
            ({"access_token": "test-token"}, "test-token", None),
            ({}, None, "Authentication token not found")
        ]

        for cookies, expected_token, expected_error in test_cases:
            mock_request = Mock()
            mock_request.cookies = cookies

            if expected_error:
                with pytest.raises(HTTPException) as exc_info:
                    get_token_from_cookie(mock_request)
                assert exc_info.value.status_code == 401
                assert expected_error in exc_info.value.detail
            else:
                token = get_token_from_cookie(mock_request)
                assert token == expected_token


class TestValidateCSRFToken:

    def test_validate_csrf_token_skip_scenarios(self) -> None:
        skip_cases: list = [
            ("GET", "/api/v1/scripts", {}, {}),
            ("HEAD", "/api/v1/scripts", {}, {}),
            ("OPTIONS", "/api/v1/scripts", {}, {}),
            ("POST", "/api/v1/login", {}, {}),
            ("POST", "/api/v1/register", {}, {}),
            ("POST", "/docs", {}, {}),
            ("POST", "/api/v1/scripts", {}, {})
        ]

        for method, path, cookies, headers in skip_cases:
            mock_request = Mock()
            mock_request.method = method
            mock_request.url = Mock()
            mock_request.url.path = path
            mock_request.cookies = cookies
            mock_request.headers = headers

            result = validate_csrf_token(mock_request)
            assert result == "skip"

    def test_validate_csrf_token_validation_scenarios(self) -> None:
        base_setup = {
            "method": "POST",
            "path": "/api/v1/scripts",
            "access_token": "test-jwt-token"
        }

        validation_cases = [
            ({}, {}, 403, "CSRF token missing"),
            ({"csrf_token": "cookie-token"}, {"X-CSRF-Token": "different-header-token"}, 403, "CSRF token invalid"),
            (
            {"csrf_token": "matching-csrf-token"}, {"X-CSRF-Token": "matching-csrf-token"}, None, "matching-csrf-token")
        ]

        for extra_cookies, headers, expected_status, expected_result in validation_cases:
            mock_request = Mock()
            mock_request.method = base_setup["method"]
            mock_request.url = Mock()
            mock_request.url.path = base_setup["path"]
            mock_request.cookies = {"access_token": base_setup["access_token"], **extra_cookies}
            mock_request.headers = headers

            if expected_status:
                with pytest.raises(HTTPException) as exc_info:
                    validate_csrf_token(mock_request)
                assert exc_info.value.status_code == expected_status
                assert expected_result in exc_info.value.detail
            else:
                result = validate_csrf_token(mock_request)
                assert result == expected_result


class TestSecurityServiceInstance:
    def test_security_service_instance(self) -> None:
        assert security_service is not None
        assert isinstance(security_service, SecurityService)
