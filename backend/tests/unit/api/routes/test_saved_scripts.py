from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock

import pytest
from app.api.routes.saved_scripts import (
    create_saved_script,
    list_saved_scripts,
    get_saved_script,
    update_saved_script,
    delete_saved_script,
    get_validated_user,
    get_script_or_404,
)
from app.schemas.saved_script import SavedScriptCreateRequest, SavedScriptResponse, SavedScriptInDB
from app.schemas.user import UserInDB
from app.services.saved_script_service import SavedScriptService
from bson import ObjectId
from fastapi import HTTPException, Request


class TestSavedScriptsRoutes:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        self.mock_request = Mock(spec=Request)
        self.mock_request.client = Mock()
        self.mock_request.client.host = "127.0.0.1"
        self.mock_saved_script_service = Mock(spec=SavedScriptService)
        self.mock_user = UserInDB(
            id=str(ObjectId()),
            username="testuser",
            email="test@example.com",
            hashed_password="hashedpass",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        self.mock_script_request = SavedScriptCreateRequest(
            name="Test Script",
            script="print('Hello, World!')",
            description="A test script"
        )
        self.mock_script_response = SavedScriptResponse(
            id=str(ObjectId()),
            name="Test Script",
            script="print('Hello, World!')",
            lang="python",
            lang_version="3.11",
            description="A test script",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

    def _create_mock_script_in_db(self,
                                  name: str = "Test Script",
                                  script: str = "print('Hello, World!')",
                                  description: str = "A test script") -> Mock:
        mock_script = Mock()
        mock_script.dict.return_value = {
            "id": str(ObjectId()),
            "user_id": str(ObjectId()),
            "name": name,
            "script": script,
            "lang": "python",
            "lang_version": "3.11",
            "description": description,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        mock_script.id = str(ObjectId())
        mock_script.name = name
        return mock_script

    def test_get_validated_user_scenarios(self) -> None:
        validation_cases = [
            (Mock(id="user123"), "user123"),
            (Mock(id=None), None)
        ]

        for user_mock, expected_id in validation_cases:
            if expected_id:
                result = get_validated_user(user_mock)
                assert result is user_mock
            else:
                with pytest.raises(HTTPException) as exc_info:
                    get_validated_user(user_mock)
                assert exc_info.value.status_code == 404
                assert exc_info.value.detail == "User not found"

    @pytest.mark.asyncio
    async def test_get_script_or_404_scenarios(self) -> None:
        script_cases = [
            (None, 404, "Script not found"),
            (Mock(id="script123"), None, None)
        ]

        for script_return, expected_status, expected_detail in script_cases:
            self.mock_saved_script_service.get_saved_script = AsyncMock(return_value=script_return)

            if expected_status:
                with pytest.raises(HTTPException) as exc_info:
                    await get_script_or_404("script_id", self.mock_user, self.mock_saved_script_service)
                assert exc_info.value.status_code == expected_status
                assert exc_info.value.detail == expected_detail
            else:
                result = await get_script_or_404("script_id", self.mock_user, self.mock_saved_script_service)
                assert result is script_return

    @pytest.mark.asyncio
    async def test_create_saved_script_scenarios(self) -> None:
        create_cases = [
            (self.mock_user, self._create_mock_script_in_db(), None, None),
            (Mock(id=None, username="testuser", email="test@example.com", hashed_password="hashedpass",
                  created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)),
             self._create_mock_script_in_db(), None, None),
            (self.mock_user, Exception("Database error"), 500, "Failed to create script")
        ]

        for user, service_result, expected_status, expected_detail in create_cases:
            self.mock_saved_script_service.reset_mock()

            if isinstance(service_result, Exception):
                self.mock_saved_script_service.create_saved_script = AsyncMock(side_effect=service_result)
            else:
                self.mock_saved_script_service.create_saved_script = AsyncMock(return_value=service_result)

            with patch('app.api.routes.saved_scripts.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with pytest.raises(HTTPException) as exc_info:
                        await create_saved_script(
                            self.mock_request, self.mock_script_request, user,
                            self.mock_saved_script_service, "valid_csrf_token"
                        )
                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == expected_detail
                else:
                    result = await create_saved_script(
                        self.mock_request, self.mock_script_request, user,
                        self.mock_saved_script_service, "valid_csrf_token"
                    )
                    assert result.name == "Test Script"

                    if user.id is None:
                        self.mock_saved_script_service.create_saved_script.assert_called_once_with(
                            self.mock_script_request, ""
                        )
                    else:
                        self.mock_saved_script_service.create_saved_script.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_saved_scripts_scenarios(self) -> None:
        list_cases = [
            ([self._create_mock_script_in_db("Script 1", "print('1')", "First script"),
              self._create_mock_script_in_db("Script 2", "print('2')", "Second script")], None, None),
            (Exception("Database error"), 500, "Failed to list scripts")
        ]

        for service_result, expected_status, expected_detail in list_cases:
            if isinstance(service_result, Exception):
                self.mock_saved_script_service.list_saved_scripts = AsyncMock(side_effect=service_result)
            else:
                self.mock_saved_script_service.list_saved_scripts = AsyncMock(return_value=service_result)

            with patch('app.api.routes.saved_scripts.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with pytest.raises(HTTPException) as exc_info:
                        await list_saved_scripts(self.mock_request, self.mock_user, self.mock_saved_script_service)
                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == expected_detail
                else:
                    result = await list_saved_scripts(self.mock_request, self.mock_user, self.mock_saved_script_service)
                    assert len(result) == 2
                    assert result[0].name == "Script 1"
                    assert result[1].name == "Script 2"

    @pytest.mark.asyncio
    async def test_get_saved_script_success(self) -> None:
        mock_script_in_db = SavedScriptInDB(
            id=str(ObjectId()),
            user_id=str(ObjectId()),
            name="Test Script",
            script="print('Hello, World!')",
            lang="python",
            lang_version="3.11",
            description="A test script",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        with patch('app.api.routes.saved_scripts.get_remote_address', return_value="127.0.0.1"):
            result = await get_saved_script(self.mock_request, mock_script_in_db)
            assert result == mock_script_in_db

    @pytest.mark.asyncio
    async def test_update_saved_script_scenarios(self) -> None:
        update_cases = [
            (self._create_mock_script_in_db("Updated Script", "print('Updated!')", "Updated description"), None, None),
            (None, 500, "Failed to update script"),
            (Exception("Database error"), 500, "Failed to update script")
        ]

        for service_result, expected_status, expected_detail in update_cases:
            self.mock_saved_script_service.reset_mock()

            if isinstance(service_result, Exception):
                self.mock_saved_script_service.update_saved_script = AsyncMock(side_effect=service_result)
            else:
                self.mock_saved_script_service.update_saved_script = AsyncMock()
                self.mock_saved_script_service.get_saved_script = AsyncMock(return_value=service_result)

            with patch('app.api.routes.saved_scripts.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with pytest.raises(HTTPException) as exc_info:
                        await update_saved_script(
                            self.mock_request, "script_id", self.mock_script_request,
                            self.mock_script_response, self.mock_user,
                            self.mock_saved_script_service, "valid_csrf_token"
                        )
                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == expected_detail
                else:
                    result = await update_saved_script(
                        self.mock_request, "script_id", self.mock_script_request,
                        self.mock_script_response, self.mock_user,
                        self.mock_saved_script_service, "valid_csrf_token"
                    )
                    assert result.name == "Updated Script"
                    self.mock_saved_script_service.update_saved_script.assert_called_once()
                    self.mock_saved_script_service.get_saved_script.assert_called_once_with("script_id",
                                                                                            self.mock_user.id)

    @pytest.mark.asyncio
    async def test_delete_saved_script_scenarios(self) -> None:
        delete_cases = [
            (None, None, None),
            (Exception("Database error"), 500, "Failed to delete script")
        ]

        for service_result, expected_status, expected_detail in delete_cases:
            if isinstance(service_result, Exception):
                self.mock_saved_script_service.delete_saved_script = AsyncMock(side_effect=service_result)
            else:
                self.mock_saved_script_service.delete_saved_script = AsyncMock()

            with patch('app.api.routes.saved_scripts.get_remote_address', return_value="127.0.0.1"):
                if expected_status:
                    with pytest.raises(HTTPException) as exc_info:
                        await delete_saved_script(
                            self.mock_request, "script_id", self.mock_script_response,
                            self.mock_user, self.mock_saved_script_service, "valid_csrf_token"
                        )
                    assert exc_info.value.status_code == expected_status
                    assert exc_info.value.detail == expected_detail
                else:
                    result = await delete_saved_script(
                        self.mock_request, "script_id", self.mock_script_response,
                        self.mock_user, self.mock_saved_script_service, "valid_csrf_token"
                    )
                    assert result is None
                    self.mock_saved_script_service.delete_saved_script.assert_called_once_with("script_id",
                                                                                               self.mock_user.id)
