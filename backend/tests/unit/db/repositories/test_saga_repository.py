import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.repositories.saga_repository import SagaRepository
from app.domain.saga.models import Saga, SagaFilter, SagaListResult


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> SagaRepository:
    return SagaRepository(mock_db)


@pytest.mark.asyncio
async def test_get_saga_and_list(repo: SagaRepository, mock_db) -> None:
    now = datetime.now(timezone.utc)
    doc = {"saga_id": "s1", "saga_name": "test_saga", "execution_id": "e1", "state": "running", "created_at": now, "updated_at": now}
    mock_db.sagas.find_one = AsyncMock(return_value=doc)
    saga = await repo.get_saga("s1")
    assert saga and saga.saga_id == "s1"

    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs

    mock_db.sagas.find.return_value = Cursor([doc])
    res = await repo.get_sagas_by_execution("e1")
    assert len(res) == 1 and res[0].execution_id == "e1"


@pytest.mark.asyncio
async def test_get_saga_not_found_and_list_error(repo: SagaRepository, mock_db) -> None:
    mock_db.sagas.find_one = AsyncMock(return_value=None)
    assert await repo.get_saga("missing") is None

    mock_db.sagas.find = AsyncMock(side_effect=Exception("boom"))
    assert await repo.get_sagas_by_execution("e", state=None) == []


@pytest.mark.asyncio
async def test_list_sagas_with_filter(repo: SagaRepository, mock_db) -> None:
    f = SagaFilter(execution_ids=["e1"])
    mock_db.sagas.count_documents = AsyncMock(return_value=2)

    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs

    now = datetime.now(timezone.utc)
    mock_db.sagas.find.return_value = Cursor([{"saga_id": "s1", "saga_name": "test_saga1", "execution_id": "e1", "state": "running", "created_at": now, "updated_at": now}, {"saga_id": "s2", "saga_name": "test_saga2", "execution_id": "e2", "state": "completed", "created_at": now, "updated_at": now}])
    result = await repo.list_sagas(f, limit=2)
    assert isinstance(result, SagaListResult) and result.total == 2 and len(result.sagas) == 2


@pytest.mark.asyncio
async def test_list_sagas_error(repo: SagaRepository, mock_db) -> None:
    mock_db.sagas.count_documents = AsyncMock(side_effect=Exception("boom"))
    res = await repo.list_sagas(SagaFilter(), limit=1)
    assert isinstance(res, SagaListResult) and res.total == 0 and res.sagas == []


@pytest.mark.asyncio
async def test_update_saga_state(repo: SagaRepository, mock_db) -> None:
    mock_db.sagas.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    assert await repo.update_saga_state("s1", "completed", error_message=None) is True


@pytest.mark.asyncio
async def test_get_user_execution_ids_and_counts(repo: SagaRepository, mock_db) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        async def to_list(self, *_a, **_k):
            return self._docs

    mock_db.executions.find.return_value = Cursor([{ "execution_id": "e1"}, {"execution_id": "e2"}])
    ids = await repo.get_user_execution_ids("u1")
    assert ids == ["e1", "e2"]

    # count by state aggregation
    class Agg:
        def __init__(self, docs):
            self._docs = docs
        async def __aiter__(self):  # pragma: no cover
            for d in self._docs:
                yield d
        def __aiter__(self):  # type: ignore[func-returns-value]
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    async def agg_iter(pipeline):  # noqa: ARG001
        for d in [{"_id": "completed", "count": 3}]:
            yield d

    mock_db.sagas.aggregate = MagicMock(return_value=Agg([{"_id": "completed", "count": 3}]))

    counts = await repo.count_sagas_by_state()
    assert counts.get("completed") == 3


@pytest.mark.asyncio
async def test_get_saga_statistics(repo: SagaRepository, mock_db) -> None:
    mock_db.sagas.count_documents = AsyncMock(return_value=5)

    class Agg:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    # state distribution
    mock_db.sagas.aggregate = MagicMock(side_effect=[Agg([{"_id": "completed", "count": 3}]), Agg([{"avg_duration": 2000}])])
    stats = await repo.get_saga_statistics()
    assert stats["total"] == 5 and stats["by_state"]["completed"] == 3 and stats["average_duration_seconds"] == 2.0


@pytest.mark.asyncio
async def test_get_saga_statistics_error_defaults(repo: SagaRepository, mock_db) -> None:
    mock_db.sagas.count_documents = AsyncMock(side_effect=Exception("boom"))
    stats = await repo.get_saga_statistics()
    assert stats == {"total": 0, "by_state": {}, "average_duration_seconds": 0.0}
