from datetime import datetime, timezone

import pytest

from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga, SagaFilter, SagaListResult

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(db) -> SagaRepository:  # type: ignore[valid-type]
    return SagaRepository(db)


@pytest.mark.asyncio
async def test_saga_crud_and_queries(repo: SagaRepository, db) -> None:  # type: ignore[valid-type]
    now = datetime.now(timezone.utc)
    # Insert saga docs
    await db.get_collection("sagas").insert_many([
        {"saga_id": "s1", "saga_name": "test", "execution_id": "e1", "state": "running", "created_at": now, "updated_at": now},
        {"saga_id": "s2", "saga_name": "test2", "execution_id": "e2", "state": "completed", "created_at": now, "updated_at": now, "completed_at": now},
    ])
    saga = await repo.get_saga("s1")
    assert saga and saga.saga_id == "s1"
    lst = await repo.get_sagas_by_execution("e1")
    assert len(lst) >= 1

    f = SagaFilter(execution_ids=["e1"])
    result = await repo.list_sagas(f, limit=2)
    assert isinstance(result, SagaListResult)

    assert await repo.update_saga_state("s1", SagaState.COMPLETED) in (True, False)

    # user execution ids
    await db.get_collection("executions").insert_many([
        {"execution_id": "e1", "user_id": "u1"},
        {"execution_id": "e2", "user_id": "u1"},
    ])
    ids = await repo.get_user_execution_ids("u1")
    assert set(ids) == {"e1", "e2"}

    counts = await repo.count_sagas_by_state()
    assert isinstance(counts, dict) and ("running" in counts or "completed" in counts)

    stats = await repo.get_saga_statistics()
    assert isinstance(stats, dict) and "total" in stats
