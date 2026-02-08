import logging
from uuid import uuid4

import pytest
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums import ExecutionStatus
from app.domain.execution import DomainExecutionCreate, DomainExecutionUpdate

_test_logger = logging.getLogger("test.db.repositories.execution_repository")

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_execution_crud_and_query() -> None:
    repo = ExecutionRepository(logger=_test_logger)
    user_id = str(uuid4())

    # Create
    create_data = DomainExecutionCreate(
        script="print('hello')",
        lang="python",
        lang_version="3.11",
        user_id=user_id,
    )
    created = await repo.create_execution(create_data)
    assert created.execution_id

    # Get
    got = await repo.get_execution(created.execution_id)
    assert got and got.script.startswith("print") and got.status == ExecutionStatus.QUEUED

    # Update
    update = DomainExecutionUpdate(status=ExecutionStatus.RUNNING, stdout="ok")
    ok = await repo.update_execution(created.execution_id, update)
    assert ok is True
    got2 = await repo.get_execution(created.execution_id)
    assert got2 and got2.status == ExecutionStatus.RUNNING

    # List
    items = await repo.get_executions({"user_id": user_id}, limit=10, skip=0, sort=[("created_at", 1)])
    assert any(x.execution_id == created.execution_id for x in items)

    # Delete
    assert await repo.delete_execution(created.execution_id) is True
    assert await repo.get_execution(created.execution_id) is None
