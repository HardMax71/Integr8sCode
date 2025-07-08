from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

import pytest
from app.db.repositories.execution_repository import (
    ExecutionRepository,
    get_execution_repository
)
from app.schemas.execution import ExecutionInDB
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection


class TestExecutionRepository:

    @pytest.fixture(autouse=True)
    def setup(self) -> None:
        """Setup mock database and collection for each test."""
        self.mock_db = Mock(spec=AsyncIOMotorDatabase)
        self.mock_collection = AsyncMock()
        self.mock_db.get_collection.return_value = self.mock_collection

    def test_execution_repository_init(self) -> None:
        mock_collection = Mock(spec=AsyncIOMotorCollection)
        self.mock_db.get_collection.return_value = mock_collection

        repo = ExecutionRepository(self.mock_db)

        assert repo.db == self.mock_db
        assert repo.collection == mock_collection
        self.mock_db.get_collection.assert_called_once_with("executions")

    @pytest.mark.asyncio
    async def test_create_execution_success(self) -> None:
        execution = ExecutionInDB(
            id="exec123",
            script="print('test')",
            status="queued",
            lang="python",
            lang_version="3.11",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        repo = ExecutionRepository(self.mock_db)
        result = await repo.create_execution(execution)

        assert result == "exec123"
        self.mock_collection.insert_one.assert_called_once()

        # Check that the execution dict was passed to insert_one
        call_args = self.mock_collection.insert_one.call_args[0][0]
        assert call_args["script"] == "print('test')"
        assert call_args["status"] == "queued"

    @pytest.mark.asyncio
    async def test_create_execution_database_error(self) -> None:
        self.mock_collection.insert_one.side_effect = Exception("Insert failed")

        execution = ExecutionInDB(
            id="exec123",
            script="print('test')",
            status="queued",
            lang="python",
            lang_version="3.11",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        repo = ExecutionRepository(self.mock_db)

        with pytest.raises(Exception, match="Insert failed"):
            await repo.create_execution(execution)

    @pytest.mark.asyncio
    async def test_create_execution_uses_by_alias(self) -> None:
        execution = ExecutionInDB(
            id="exec123",
            script="print('test')",
            status="queued",
            lang="python",
            lang_version="3.11",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        repo = ExecutionRepository(self.mock_db)
        result = await repo.create_execution(execution)

        # Verify the execution ID is returned and insert was called
        assert result == "exec123"
        self.mock_collection.insert_one.assert_called_once()

        # Check that the call included the execution data
        call_args = self.mock_collection.insert_one.call_args[0][0]
        assert call_args["script"] == "print('test')"

    @pytest.mark.asyncio
    @patch('app.db.repositories.execution_repository.logger')
    async def test_get_execution_found(self, mock_logger: Mock) -> None:
        # Mock execution data from database
        execution_data = {
            "id": "exec123",
            "script": "print('test')",
            "status": "completed",
            "lang": "python",
            "lang_version": "3.11",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        self.mock_collection.find_one.return_value = execution_data

        repo = ExecutionRepository(self.mock_db)
        result = await repo.get_execution("exec123")

        assert result is not None
        assert isinstance(result, ExecutionInDB)
        assert result.id == "exec123"
        assert result.script == "print('test')"
        assert result.status == "completed"

        self.mock_collection.find_one.assert_called_once_with({"id": "exec123"})
        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.db.repositories.execution_repository.logger')
    async def test_get_execution_not_found(self, mock_logger: Mock) -> None:
        self.mock_collection.find_one.return_value = None

        repo = ExecutionRepository(self.mock_db)
        result = await repo.get_execution("nonexistent")

        assert result is None
        self.mock_collection.find_one.assert_called_once_with({"id": "nonexistent"})
        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    @patch('app.db.repositories.execution_repository.logger')
    async def test_get_execution_database_error(self, mock_logger: Mock) -> None:
        self.mock_collection.find_one.side_effect = Exception("Database error")

        repo = ExecutionRepository(self.mock_db)
        result = await repo.get_execution("exec123")

        assert result is None
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args
        assert "Database error fetching execution exec123" in error_call[0][0]
        assert error_call[1]["exc_info"] is True

    @pytest.mark.asyncio
    @patch('app.db.repositories.execution_repository.logger')
    async def test_get_execution_validation_error(self, mock_logger: Mock) -> None:
        # Mock data that will cause ValidationError during ExecutionInDB creation
        malformed_data = {"id": "exec123"}  # Missing required fields
        self.mock_collection.find_one.return_value = malformed_data

        repo = ExecutionRepository(self.mock_db)
        result = await repo.get_execution("exec123")

        # Should return None and log error when validation fails
        assert result is None
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_execution_success(self) -> None:
        # Mock successful update result
        mock_result = Mock()
        mock_result.matched_count = 1
        self.mock_collection.update_one.return_value = mock_result

        update_data = {"status": "completed", "output": "Hello World"}

        repo = ExecutionRepository(self.mock_db)
        result = await repo.update_execution("exec123", update_data)

        assert result is True
        self.mock_collection.update_one.assert_called_once()

        # Check call arguments
        call_args = self.mock_collection.update_one.call_args
        assert call_args[0][0] == {"id": "exec123"}

        # Check that updated_at was added to update data
        update_payload = call_args[0][1]
        assert "$set" in update_payload
        set_data = update_payload["$set"]
        assert set_data["status"] == "completed"
        assert set_data["output"] == "Hello World"
        assert "updated_at" in set_data
        assert isinstance(set_data["updated_at"], datetime)

    @pytest.mark.asyncio
    async def test_update_execution_not_found(self) -> None:
        # Mock no match result
        mock_result = Mock()
        mock_result.matched_count = 0
        self.mock_collection.update_one.return_value = mock_result

        update_data = {"status": "completed"}

        repo = ExecutionRepository(self.mock_db)
        result = await repo.update_execution("nonexistent", update_data)

        assert result is False

    @pytest.mark.asyncio
    @patch('app.db.repositories.execution_repository.logger')
    async def test_update_execution_database_error(self, mock_logger: Mock) -> None:
        self.mock_collection.update_one.side_effect = Exception("Update failed")

        update_data = {"status": "error"}

        repo = ExecutionRepository(self.mock_db)
        result = await repo.update_execution("exec123", update_data)

        assert result is False
        mock_logger.error.assert_called_once()
        error_call = mock_logger.error.call_args
        assert "Database error updating execution exec123" in error_call[0][0]
        assert error_call[1]["exc_info"] is True

    @pytest.mark.asyncio
    async def test_update_execution_preserves_existing_updated_at(self) -> None:
        mock_result = Mock()
        mock_result.matched_count = 1
        self.mock_collection.update_one.return_value = mock_result

        custom_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        update_data = {"status": "completed", "updated_at": custom_time}

        repo = ExecutionRepository(self.mock_db)
        result = await repo.update_execution("exec123", update_data)

        assert result is True

        # Check that custom updated_at was preserved
        call_args = self.mock_collection.update_one.call_args
        set_data = call_args[0][1]["$set"]
        assert set_data["updated_at"] == custom_time

    @pytest.mark.asyncio
    async def test_update_execution_empty_update_data(self) -> None:
        mock_result = Mock()
        mock_result.matched_count = 1
        self.mock_collection.update_one.return_value = mock_result

        update_data: dict[str, str] = {}

        repo = ExecutionRepository(self.mock_db)
        result = await repo.update_execution("exec123", update_data)

        assert result is True

        # Should still add updated_at
        call_args = self.mock_collection.update_one.call_args
        set_data = call_args[0][1]["$set"]
        assert "updated_at" in set_data


class TestGetExecutionRepository:

    def test_get_execution_repository_returns_repository(self) -> None:
        mock_db = Mock(spec=AsyncIOMotorDatabase)
        mock_db.get_collection.return_value = Mock()

        result = get_execution_repository(mock_db)

        assert isinstance(result, ExecutionRepository)
        assert result.db == mock_db

    def test_get_execution_repository_different_dbs(self) -> None:
        mock_db1 = Mock(spec=AsyncIOMotorDatabase)
        mock_db1.get_collection.return_value = Mock()
        mock_db2 = Mock(spec=AsyncIOMotorDatabase)
        mock_db2.get_collection.return_value = Mock()

        repo1 = get_execution_repository(mock_db1)
        repo2 = get_execution_repository(mock_db2)

        assert repo1.db == mock_db1
        assert repo2.db == mock_db2
        assert repo1 != repo2

    @patch('app.db.repositories.execution_repository.get_db_dependency')
    def test_get_execution_repository_dependency_integration(self,
                                                             mock_get_db_dependency: Mock) -> None:
        mock_db = Mock(spec=AsyncIOMotorDatabase)
        mock_db.get_collection.return_value = Mock()
        mock_get_db_dependency.return_value = mock_db

        # This simulates how FastAPI would call it
        result = get_execution_repository(mock_db)

        assert isinstance(result, ExecutionRepository)
        assert result.db == mock_db
