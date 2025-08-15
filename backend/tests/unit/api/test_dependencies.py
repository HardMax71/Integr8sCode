from unittest.mock import Mock, patch

import pytest

from app.config import Settings, get_settings
from app.core.database_context import DatabaseProvider
from app.core.service_dependencies import DatabaseManager, get_database, get_database_manager


class TestDependenciesFullCoverage:

    def test_get_settings_dependency(self) -> None:
        with patch('app.api.dependencies.get_settings') as mock_get_settings:
            mock_settings = Mock(spec=Settings)
            mock_get_settings.return_value = mock_settings

            result = get_settings()

            assert result == mock_settings
            mock_get_settings.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_database_dependency_success(self) -> None:
        mock_provider = Mock(spec=DatabaseProvider)
        mock_database = Mock()
        mock_provider.database = mock_database

        result = await get_database(mock_provider)

        assert result == mock_database

    @pytest.mark.asyncio
    async def test_get_database_manager_dependency_success(self) -> None:
        mock_provider = Mock(spec=DatabaseProvider)
        mock_db_manager = Mock(spec=DatabaseManager)

        with patch('app.core.service_dependencies.DatabaseManager.from_provider', return_value=mock_db_manager):
            result = await get_database_manager(mock_provider)

        assert result == mock_db_manager

    @pytest.mark.asyncio
    async def test_get_database_with_provider_error(self) -> None:
        mock_provider = Mock(spec=DatabaseProvider)
        mock_provider.database = None

        result = await get_database(mock_provider)

        assert result is None
