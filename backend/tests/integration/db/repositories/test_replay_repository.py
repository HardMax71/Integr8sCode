from datetime import datetime, timezone

import pytest
from app.db.repositories.replay_repository import ReplayRepository
from app.domain.admin.replay_updates import ReplaySessionUpdate
from app.domain.enums.replay import ReplayStatus, ReplayType
from app.domain.replay import ReplayConfig, ReplayFilter
from app.schemas_pydantic.replay_models import ReplaySession

pytestmark = pytest.mark.integration


@pytest.fixture()
async def repo(scope) -> ReplayRepository:  # type: ignore[valid-type]
    return await scope.get(ReplayRepository)


@pytest.mark.asyncio
async def test_indexes_and_session_crud(repo: ReplayRepository) -> None:
    await repo.create_indexes()
    config = ReplayConfig(replay_type=ReplayType.EXECUTION, filter=ReplayFilter())
    session = ReplaySession(
        session_id="s1", status=ReplayStatus.CREATED, created_at=datetime.now(timezone.utc), config=config
    )
    await repo.save_session(session)
    got = await repo.get_session("s1")
    assert got and got.session_id == "s1"
    lst = await repo.list_sessions(limit=5)
    assert any(s.session_id == "s1" for s in lst)
    assert await repo.update_session_status("s1", ReplayStatus.RUNNING) is True
    session_update = ReplaySessionUpdate(status=ReplayStatus.COMPLETED)
    assert await repo.update_replay_session("s1", session_update) is True


@pytest.mark.asyncio
async def test_count_fetch_events_and_delete(repo: ReplayRepository, db) -> None:  # type: ignore[valid-type]
    now = datetime.now(timezone.utc)
    # Insert events
    await db.get_collection("events").insert_many(
        [
            {
                "event_id": "e1",
                "timestamp": now,
                "execution_id": "x1",
                "event_type": "T",
                "metadata": {"user_id": "u1"},
            },
            {
                "event_id": "e2",
                "timestamp": now,
                "execution_id": "x2",
                "event_type": "T",
                "metadata": {"user_id": "u1"},
            },
            {
                "event_id": "e3",
                "timestamp": now,
                "execution_id": "x3",
                "event_type": "U",
                "metadata": {"user_id": "u2"},
            },
        ]
    )
    cnt = await repo.count_events(ReplayFilter())
    assert cnt >= 3
    batches = []
    async for b in repo.fetch_events(ReplayFilter(), batch_size=2):
        batches.append(b)
    assert sum(len(b) for b in batches) >= 3
    # Delete old sessions (none match date predicate likely)
    assert await repo.delete_old_sessions(datetime(2000, 1, 1, tzinfo=timezone.utc)) >= 0
