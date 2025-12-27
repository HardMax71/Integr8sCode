import pytest
from uuid import uuid4
from datetime import datetime, timezone

from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.execution import ExecutionStatus
from app.domain.execution.models import DomainExecution, ResourceUsageDomain


@pytest.mark.asyncio
async def test_execution_crud_and_query(db) -> None:  # type: ignore[valid-type]
    repo = ExecutionRepository(db)

    # Create
    e = DomainExecution(
        script="print('hello')",
        lang="python",
        lang_version="3.11",
        user_id=str(uuid4()),
        resource_usage=ResourceUsageDomain(0.0, 0, 0, 0),
    )
    created = await repo.create_execution(e)
    assert created.execution_id

    # Get
    got = await repo.get_execution(e.execution_id)
    assert got and got.script.startswith("print") and got.status == ExecutionStatus.QUEUED

    # Update
    ok = await repo.update_execution(e.execution_id, {"status": ExecutionStatus.RUNNING.value, "stdout": "ok"})
    assert ok is True
    got2 = await repo.get_execution(e.execution_id)
    assert got2 and got2.status == ExecutionStatus.RUNNING

    # List
    items = await repo.get_executions({"user_id": e.user_id}, limit=10, skip=0, sort=[("created_at", 1)])
    assert any(x.execution_id == e.execution_id for x in items)

    # Delete
    assert await repo.delete_execution(e.execution_id) is True
    assert await repo.get_execution(e.execution_id) is None
