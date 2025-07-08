from unittest.mock import Mock, patch

import pytest
from app.api.dependencies import get_settings_dependency, get_db_dependency
from app.config import Settings
from app.db.mongodb import DatabaseManager
from fastapi import HTTPException, Request


class TestDependenciesFullCoverage:

    def test_get_settings_dependency(self) -> None:
        with patch('app.api.dependencies.get_settings') as mock_get_settings:
            mock_settings = Mock(spec=Settings)
            mock_get_settings.return_value = mock_settings

            result = get_settings_dependency()

            assert result == mock_settings
            mock_get_settings.assert_called_once()

    def test_get_db_dependency_success(self) -> None:
        mock_request = Mock(spec=Request)
        mock_db_manager = Mock(spec=DatabaseManager)
        mock_database = Mock()

        mock_request.app.state.db_manager = mock_db_manager
        mock_db_manager.get_database.return_value = mock_database

        result = get_db_dependency(mock_request)

        assert result == mock_database
        mock_db_manager.get_database.assert_called_once()

    def test_get_db_dependency_attribute_error(self) -> None:
        mock_request = Mock(spec=Request)
        # Remove db_manager from app.state to trigger AttributeError
        del mock_request.app.state.db_manager

        with pytest.raises(HTTPException) as exc_info:
            get_db_dependency(mock_request)

        assert exc_info.value.status_code == 500
        assert "Database service not available" in exc_info.value.detail

    def test_get_db_dependency_runtime_error(self) -> None:
        mock_request = Mock(spec=Request)
        mock_db_manager = Mock(spec=DatabaseManager)

        mock_request.app.state.db_manager = mock_db_manager
        mock_db_manager.get_database.side_effect = RuntimeError("Database connection failed")

        with pytest.raises(HTTPException) as exc_info:
            get_db_dependency(mock_request)

        assert exc_info.value.status_code == 500
        assert "Database connection issue" in exc_info.value.detail
