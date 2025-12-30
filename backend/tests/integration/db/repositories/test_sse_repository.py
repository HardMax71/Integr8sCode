import pytest
from app.db.repositories.sse_repository import SSERepository
from app.domain.enums.execution import ExecutionStatus

pytestmark = pytest.mark.integration


@pytest.fixture()
async def repo(scope) -> SSERepository:  # type: ignore[valid-type]
    return await scope.get(SSERepository)


@pytest.mark.asyncio
async def test_get_execution_status(repo: SSERepository, db) -> None:  # type: ignore[valid-type]
    await db.get_collection("executions").insert_one({"execution_id": "e1", "status": "running"})
    status = await repo.get_execution_status("e1")
    assert status is not None
    assert status.status == ExecutionStatus.RUNNING
    assert status.execution_id == "e1"


@pytest.mark.asyncio
async def test_get_execution_status_none(repo: SSERepository, db) -> None:  # type: ignore[valid-type]
    assert await repo.get_execution_status("missing") is None


@pytest.mark.asyncio
async def test_get_execution(repo: SSERepository, db) -> None:  # type: ignore[valid-type]
    await db.get_collection("executions").insert_one({"execution_id": "e1", "status": "queued", "resource_usage": {}})
    doc = await repo.get_execution("e1")
    assert doc is not None
    assert doc.execution_id == "e1"


@pytest.mark.asyncio
async def test_get_execution_not_found(repo: SSERepository, db) -> None:  # type: ignore[valid-type]
    assert await repo.get_execution("missing") is None
