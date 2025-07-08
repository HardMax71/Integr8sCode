from unittest.mock import Mock, patch, AsyncMock, MagicMock

import pytest
from app.config import get_settings, Settings
from app.db.mongodb import DatabaseManager
from motor.motor_asyncio import AsyncIOMotorDatabase


class TestDatabaseManagerExtended:

    @pytest.fixture
    def mock_settings(self) -> Settings:
        settings = get_settings()
        settings.TESTING = True
        settings.PROJECT_NAME = "test_project"
        settings.MONGODB_URL = "mongodb://localhost:27017"
        return settings

    def test_database_manager_initialization(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        assert manager.settings is mock_settings
        assert hasattr(manager, 'db_name')
        assert manager.db_name == "test_project_test"
        assert manager.client is None
        assert manager.db is None

    def test_database_manager_with_none_settings(self) -> None:
        with pytest.raises(AttributeError):
            # Should fail because None doesn't have TESTING or PROJECT_NAME attributes
            manager = DatabaseManager(None)

    def test_database_manager_different_settings(self, mock_settings: Settings) -> None:
        settings2 = get_settings()
        settings2.TESTING = False
        settings2.PROJECT_NAME = "other_project"

        manager1 = DatabaseManager(mock_settings)
        manager2 = DatabaseManager(settings2)

        assert manager1.db_name == "test_project_test"
        assert manager2.db_name == "other_project"
        assert manager1.settings is not manager2.settings

    def test_database_manager_testing_vs_production_db_name(self) -> None:
        # Testing mode
        settings_test = get_settings()
        settings_test.TESTING = True
        settings_test.PROJECT_NAME = "myapp"
        manager_test = DatabaseManager(settings_test)
        assert manager_test.db_name == "myapp_test"

        # Production mode
        settings_prod = get_settings()
        settings_prod.TESTING = False
        settings_prod.PROJECT_NAME = "myapp"
        manager_prod = DatabaseManager(settings_prod)
        assert manager_prod.db_name == "myapp"

    @pytest.mark.asyncio
    async def test_connect_to_database_success(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        # Mock the motor client and its methods
        with patch('app.db.mongodb.AsyncIOMotorClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # Mock admin command for ping
            mock_client.admin.command = AsyncMock(return_value={"ok": 1})

            # Mock database access
            mock_db = Mock(spec=AsyncIOMotorDatabase)
            mock_client.__getitem__.return_value = mock_db

            await manager.connect_to_database()

            # Verify connection was established
            assert manager.client is mock_client
            assert manager.db is mock_db
            mock_client.admin.command.assert_called_once_with("ping")

    @pytest.mark.asyncio
    async def test_connect_to_database_failure_then_success(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        with patch('app.db.mongodb.AsyncIOMotorClient') as mock_client_class, \
                patch('asyncio.sleep') as mock_sleep:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            # First call raises exception, second succeeds
            mock_client.admin.command = AsyncMock(
                side_effect=[Exception("Connection failed"), {"ok": 1}]
            )

            # Mock database access
            mock_db = Mock(spec=AsyncIOMotorDatabase)
            mock_client.__getitem__.return_value = mock_db

            await manager.connect_to_database(retries=2, retry_delay=0.1)

            # Should have succeeded on second attempt
            assert manager.client is mock_client
            assert manager.db is mock_db
            assert mock_client.admin.command.call_count == 2
            mock_sleep.assert_called_once_with(0.1)

    @pytest.mark.asyncio
    async def test_connect_to_database_all_retries_fail(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        with patch('app.db.mongodb.AsyncIOMotorClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.close = Mock()  # Add close method

            # All attempts fail
            mock_client.admin.command = AsyncMock(
                side_effect=Exception("Connection failed")
            )

            with pytest.raises(ConnectionError, match="Could not connect to MongoDB"):
                await manager.connect_to_database(retries=2, retry_delay=0.01)

            # Client should remain None after failed connection
            assert manager.client is None
            assert manager.db is None
            # Client should be closed on failure
            mock_client.close.assert_called()

    @pytest.mark.asyncio
    async def test_close_database_connection_with_client(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        # Set up a mock client
        mock_client = Mock()
        mock_client.close = Mock()
        manager.client = mock_client
        manager.db = Mock()

        await manager.close_database_connection()

        # Should close client and reset attributes
        mock_client.close.assert_called_once()
        assert manager.client is None
        assert manager.db is None

    @pytest.mark.asyncio
    async def test_close_database_connection_without_client(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        # No client set
        assert manager.client is None

        # Should not raise any errors
        await manager.close_database_connection()

        assert manager.client is None
        assert manager.db is None

    @pytest.mark.asyncio
    async def test_close_database_connection_with_exception(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        # Set up a mock client that raises exception on close
        mock_client = Mock()
        mock_client.close = Mock(side_effect=Exception("Close failed"))
        manager.client = mock_client
        manager.db = Mock()

        # Should not raise exception, just log it
        await manager.close_database_connection()

        mock_client.close.assert_called_once()

    def test_get_database_success(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        # Set up database
        mock_db = Mock(spec=AsyncIOMotorDatabase)
        manager.db = mock_db

        result = manager.get_database()
        assert result is mock_db

    def test_get_database_not_connected(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        # No database set
        assert manager.db is None

        with pytest.raises(RuntimeError, match="Database is not connected"):
            manager.get_database()

    def test_database_manager_attributes(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        assert hasattr(manager, 'settings')
        assert hasattr(manager, 'db_name')
        assert hasattr(manager, 'client')
        assert hasattr(manager, 'db')

    def test_database_manager_multiple_instances(self, mock_settings: Settings) -> None:
        manager1 = DatabaseManager(mock_settings)
        manager2 = DatabaseManager(mock_settings)

        # Should be different instances
        assert manager1 is not manager2
        assert manager1.client is manager2.client  # Both None initially
        assert manager1.db is manager2.db  # Both None initially

        # Modifying one shouldn't affect the other
        manager1.client = Mock()
        assert manager1.client is not manager2.client


class TestDatabaseManagerIntegration:

    @pytest.fixture
    def mock_settings(self) -> Settings:
        settings = get_settings()
        settings.TESTING = True
        settings.PROJECT_NAME = "integration_test"
        settings.MONGODB_URL = "mongodb://localhost:27017"
        return settings

    @pytest.mark.asyncio
    async def test_database_manager_full_lifecycle(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        with patch('app.db.mongodb.AsyncIOMotorClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.admin.command = AsyncMock(return_value={"ok": 1})
            mock_client.close = Mock()

            mock_db = Mock(spec=AsyncIOMotorDatabase)
            mock_client.__getitem__.return_value = mock_db

            # Connect
            await manager.connect_to_database()
            assert manager.client is mock_client
            assert manager.db is mock_db

            # Get database
            db = manager.get_database()
            assert db is mock_db

            # Close
            await manager.close_database_connection()
            assert manager.client is None
            assert manager.db is None

    @pytest.mark.asyncio
    async def test_database_manager_connection_parameters(self, mock_settings: Settings) -> None:
        manager = DatabaseManager(mock_settings)

        with patch('app.db.mongodb.AsyncIOMotorClient') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.admin.command = AsyncMock(return_value={"ok": 1})

            mock_db = Mock(spec=AsyncIOMotorDatabase)
            mock_client.__getitem__.return_value = mock_db

            await manager.connect_to_database()

            # Verify client was created with correct parameters
            mock_client_class.assert_called_once_with(
                mock_settings.MONGODB_URL,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                maxPoolSize=50,
                retryWrites=True,
                waitQueueTimeoutMS=2500,
                uuidRepresentation='standard',
                tz_aware=True
            )
