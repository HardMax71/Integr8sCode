from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.api.routes.auth import login, register, verify_token, logout
from app.schemas.user import UserCreate
from fastapi import HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm


class TestAuthRoutesCoverage:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.mock_request = Mock(spec=Request)
        self.mock_response = Mock(spec=Response)
        self.mock_response.set_cookie = Mock()
        self.mock_response.delete_cookie = Mock()
        self.mock_user_repo = AsyncMock()

    def _setup_request(self, has_user_agent: bool = True) -> None:
        if has_user_agent:
            self.mock_request.headers = {"user-agent": "test-agent"}
        else:
            self.mock_request.headers = {}

    @pytest.mark.asyncio
    async def test_login_scenarios(self) -> None:
        login_cases = [
            ("nonexistent", "password", None, False, 401, "Invalid credentials"),
            ("testuser", "wrongpassword", Mock(username="testuser"), False, 401, "Invalid credentials"),
            ("testuser", "correctpassword", Mock(username="testuser"), True, None, None)
        ]

        for username, password, user_return, verify_password_result, expected_status, expected_detail in login_cases:
            self._setup_request()

            mock_form_data = Mock(spec=OAuth2PasswordRequestForm)
            mock_form_data.username = username
            mock_form_data.password = password

            self.mock_user_repo.get_user.return_value = user_return

            with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with patch('app.api.routes.auth.security_service.verify_password',
                               return_value=verify_password_result):
                        with pytest.raises(HTTPException) as exc_info:
                            await login(self.mock_request, self.mock_response, mock_form_data, self.mock_user_repo)

                        assert exc_info.value.status_code == expected_status
                        assert exc_info.value.detail == expected_detail
                else:
                    mock_settings = Mock(ACCESS_TOKEN_EXPIRE_MINUTES=30)
                    with patch('app.api.routes.auth.security_service.verify_password', return_value=True):
                        with patch('app.api.routes.auth.get_settings', return_value=mock_settings):
                            with patch('app.api.routes.auth.security_service.create_access_token',
                                       return_value="token"):
                                with patch('app.api.routes.auth.security_service.generate_csrf_token',
                                           return_value="csrf"):
                                    result = await login(self.mock_request, self.mock_response, mock_form_data,
                                                         self.mock_user_repo)

                                    assert result["message"] == "Login successful"
                                    assert result["username"] == "testuser"
                                    assert result["csrf_token"] == "csrf"
                                    assert self.mock_response.set_cookie.call_count == 2

            self.mock_user_repo.reset_mock()
            self.mock_response.reset_mock()

    @pytest.mark.asyncio
    async def test_register_scenarios(self) -> None:
        register_cases = [
            (Mock(), 400, "Username already registered", None),
            (None, 500, "Error creating user", Exception("Database error")),
            (None, None, None, Mock(username="newuser"))
        ]

        for existing_user, expected_status, expected_detail, create_result in register_cases:
            self._setup_request()
            mock_user_create = UserCreate(username="testuser", email="test@test.com", password="password")

            self.mock_user_repo.get_user.return_value = existing_user
            self.mock_user_repo.create_user.side_effect = None

            with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    if expected_status == 500:
                        self.mock_user_repo.create_user.side_effect = create_result
                        with patch('app.api.routes.auth.security_service.get_password_hash', return_value="hashed"):
                            with pytest.raises(HTTPException) as exc_info:
                                await register(self.mock_request, mock_user_create, self.mock_user_repo)
                    else:
                        with pytest.raises(HTTPException) as exc_info:
                            await register(self.mock_request, mock_user_create, self.mock_user_repo)

                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == expected_detail
                else:
                    self.mock_user_repo.create_user.return_value = create_result
                    with patch('app.api.routes.auth.security_service.get_password_hash', return_value="hashed"):
                        with patch('app.api.routes.auth.UserResponse.model_validate') as mock_validate:
                            mock_response = Mock()
                            mock_validate.return_value = mock_response

                            result = await register(self.mock_request, mock_user_create, self.mock_user_repo)
                            assert result == mock_response

            self.mock_user_repo.reset_mock()

    @pytest.mark.asyncio
    async def test_verify_token_scenarios(self) -> None:
        mock_current_user = Mock(username="testuser")

        verify_cases = [
            (Mock(get=Mock(side_effect=Exception("Cookie error"))), 401, "Invalid token"),
            ({"csrf_token": "csrf_value"}, None, "csrf_value"),
            ({}, None, "")
        ]

        for cookies, expected_status, expected_csrf in verify_cases:
            self._setup_request()
            self.mock_request.cookies = cookies

            with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with pytest.raises(HTTPException) as exc_info:
                        await verify_token(self.mock_request, mock_current_user)

                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == "Invalid token"
                else:
                    result = await verify_token(self.mock_request, mock_current_user)

                    assert result["valid"] is True
                    assert result["username"] == "testuser"
                    assert result["csrf_token"] == expected_csrf

    @pytest.mark.asyncio
    async def test_logout_successful(self) -> None:
        self._setup_request()

        with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
            result = await logout(self.mock_request, self.mock_response)

            assert result["message"] == "Logout successful"
            assert self.mock_response.delete_cookie.call_count == 2

    @pytest.mark.asyncio
    async def test_missing_user_agent_scenarios(self) -> None:
        endpoints = [
            ("login", lambda: login(self.mock_request, self.mock_response,
                                    Mock(spec=OAuth2PasswordRequestForm, username="test", password="pass"),
                                    self.mock_user_repo)),
            ("register", lambda: register(self.mock_request,
                                          UserCreate(username="test", email="test@test.com", password="pass"),
                                          self.mock_user_repo)),
            ("verify_token", lambda: verify_token(self.mock_request, Mock(username="testuser"))),
            ("logout", lambda: logout(self.mock_request, self.mock_response))
        ]

        for endpoint_name, endpoint_func in endpoints:
            self._setup_request(has_user_agent=False)

            if endpoint_name == "register":
                self.mock_user_repo.get_user.return_value = None
                with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                    with patch('app.api.routes.auth.security_service.get_password_hash', return_value="hashed"):
                        with patch('app.api.routes.auth.UserResponse.model_validate', return_value=Mock()):
                            self.mock_user_repo.create_user.return_value = Mock(username="test")
                            result = await endpoint_func()
                            assert result is not None
            elif endpoint_name == "verify_token":
                self.mock_request.cookies = {"csrf_token": "csrf"}
                with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                    result = await endpoint_func()
                    assert result["valid"] is True
            elif endpoint_name == "logout":
                with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                    result = await endpoint_func()
                    assert result["message"] == "Logout successful"
            else:
                self.mock_user_repo.get_user.return_value = None
                with patch('app.api.routes.auth.get_remote_address', return_value="127.0.0.1"):
                    with pytest.raises(HTTPException):
                        await endpoint_func()

            self.mock_user_repo.reset_mock()
            self.mock_response.reset_mock()
