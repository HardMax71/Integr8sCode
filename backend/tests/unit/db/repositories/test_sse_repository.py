import pytest
from unittest.mock import AsyncMock

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.repositories.sse_repository import SSERepository


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> SSERepository:
    return SSERepository(mock_db)


@pytest.mark.asyncio
async def test_get_execution_status(repo: SSERepository, mock_db) -> None:
    mock_db.executions.find_one = AsyncMock(return_value={"status": "running", "execution_id": "e1"})
    status = await repo.get_execution_status("e1")
    assert status and status.status == "running" and status.execution_id == "e1"


@pytest.mark.asyncio
async def test_get_execution_status_none(repo: SSERepository, mock_db) -> None:
    mock_db.executions.find_one = AsyncMock(return_value=None)
    assert await repo.get_execution_status("missing") is None


@pytest.mark.asyncio
async def test_get_execution_events(repo: SSERepository, mock_db) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    mock_db.events.find.return_value = Cursor([{"aggregate_id": "e1", "timestamp": 1}])
    events = await repo.get_execution_events("e1")
    assert len(events) == 1 and events[0].aggregate_id == "e1"


@pytest.mark.asyncio
async def test_get_execution_for_user_and_plain(repo: SSERepository, mock_db) -> None:
    mock_db.executions.find_one = AsyncMock(return_value={"execution_id": "e1", "user_id": "u1", "resource_usage": {}})
    doc = await repo.get_execution_for_user("e1", "u1")
    assert doc and doc.user_id == "u1"

    mock_db.executions.find_one = AsyncMock(return_value={"execution_id": "e2", "resource_usage": {}})
    assert (await repo.get_execution("e2")) is not None


@pytest.mark.asyncio
async def test_get_execution_for_user_not_found(repo: SSERepository, mock_db) -> None:
    mock_db.executions.find_one = AsyncMock(return_value=None)
    assert await repo.get_execution_for_user("e1", "uX") is None
