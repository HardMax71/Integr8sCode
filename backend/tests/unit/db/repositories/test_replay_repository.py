import pytest
from unittest.mock import AsyncMock, MagicMock

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.repositories.replay_repository import ReplayRepository
from app.schemas_pydantic.replay_models import ReplaySession
from app.domain.replay.models import ReplayFilter


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> ReplayRepository:
    return ReplayRepository(mock_db)


@pytest.mark.asyncio
async def test_create_indexes(repo: ReplayRepository, mock_db) -> None:
    mock_db.replay_sessions.create_index = AsyncMock()
    mock_db.events.create_index = AsyncMock()
    await repo.create_indexes()
    assert mock_db.replay_sessions.create_index.await_count >= 1
    assert mock_db.events.create_index.await_count >= 1


@pytest.mark.asyncio
async def test_count_sessions(repo: ReplayRepository, mock_db) -> None:
    mock_db.replay_sessions.count_documents = AsyncMock(return_value=11)
    assert await repo.count_sessions({"status": "completed"}) == 11


@pytest.mark.asyncio
async def test_save_get_list_update_delete(repo: ReplayRepository, mock_db) -> None:
    from app.domain.enums.replay import ReplayStatus, ReplayType
    from app.domain.replay.models import ReplayConfig, ReplayFilter
    from datetime import datetime, timezone
    
    config = ReplayConfig(
        replay_type=ReplayType.EXECUTION,
        filter=ReplayFilter()
    )
    session = ReplaySession(
        session_id="s1", 
        status=ReplayStatus.CREATED, 
        created_at=datetime.now(timezone.utc), 
        config=config
    )
    mock_db.replay_sessions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    await repo.save_session(session)
    mock_db.replay_sessions.update_one.assert_called_once()

    mock_db.replay_sessions.find_one = AsyncMock(return_value=session.model_dump())
    got = await repo.get_session("s1")
    assert got and got.session_id == "s1"

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

    mock_db.replay_sessions.find.return_value = Cursor([session.model_dump()])
    sessions = await repo.list_sessions(limit=5)
    assert len(sessions) == 1 and sessions[0].session_id == "s1"

    mock_db.replay_sessions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.update_session_status("s1", "running") is True

    mock_db.replay_sessions.delete_many = AsyncMock(return_value=MagicMock(deleted_count=3))
    assert await repo.delete_old_sessions("2024-01-01T00:00:00Z") == 3


@pytest.mark.asyncio
async def test_count_and_fetch_events(repo: ReplayRepository, mock_db) -> None:
    mock_db.events.count_documents = AsyncMock(return_value=7)
    count = await repo.count_events(ReplayFilter())
    assert count == 7

    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    mock_db.events.find.return_value = Cursor([{"event_id": "e1"}, {"event_id": "e2"}, {"event_id": "e3"}])
    batches = []
    async for batch in repo.fetch_events(ReplayFilter(), batch_size=2):
        batches.append(batch)
    assert sum(len(b) for b in batches) == 3 and len(batches) == 2  # 2 + 1


@pytest.mark.asyncio
async def test_update_replay_session(repo: ReplayRepository, mock_db) -> None:
    mock_db.replay_sessions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.update_replay_session("s1", {"status": "running"}) is True


@pytest.mark.asyncio
async def test_create_indexes_exception(repo: ReplayRepository, mock_db) -> None:
    mock_db.replay_sessions.create_index = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.create_indexes()


@pytest.mark.asyncio
async def test_list_sessions_with_filters(repo: ReplayRepository, mock_db) -> None:
    # Ensure status and user_id branches in query are hit
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
    mock_db.replay_sessions.find.return_value = Cursor([])
    res = await repo.list_sessions(status="running", user_id="u1", limit=5, skip=0)
    # No assertion beyond successful call; targets building query lines
    assert isinstance(res, list)
