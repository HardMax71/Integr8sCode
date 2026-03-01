from uuid import uuid4

import pytest
import structlog
from app.db.repositories import ExecutionRepository
from app.domain.enums import ExecutionErrorType, ExecutionStatus
from app.domain.execution import DomainExecutionCreate, ExecutionResultDomain

_test_logger = structlog.get_logger("test.db.repositories.execution_repository")

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

    # List
    items = await repo.get_executions({"user_id": user_id}, limit=10, skip=0, sort=[("created_at", 1)])
    assert any(x.execution_id == created.execution_id for x in items)

    # Delete
    assert await repo.delete_execution(created.execution_id) is True
    assert await repo.get_execution(created.execution_id) is None


async def _create_and_complete(
    repo: ExecutionRepository,
    user_id: str,
    *,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    lang: str = "python",
    lang_version: str = "3.11",
) -> str:
    """Helper: create an execution then transition it to a terminal status."""
    created = await repo.create_execution(DomainExecutionCreate(
        script="x = 1", lang=lang, lang_version=lang_version, user_id=user_id,
    ))
    wrote = await repo.write_terminal_result(ExecutionResultDomain(
        execution_id=created.execution_id,
        status=status,
        exit_code=0 if status == ExecutionStatus.COMPLETED else 1,
        stdout="ok",
        stderr="",
        error_type=ExecutionErrorType.SCRIPT_ERROR if status == ExecutionStatus.FAILED else None,
    ))
    assert wrote, f"write_terminal_result failed for {created.execution_id}"
    return created.execution_id


@pytest.mark.asyncio
async def test_aggregate_stats_empty() -> None:
    """Empty result set returns zero-value stats."""
    repo = ExecutionRepository(logger=_test_logger)
    bogus_user = str(uuid4())

    stats = await repo.aggregate_stats({"user_id": bogus_user})

    assert stats["total"] == 0
    assert stats["by_status"] == {}
    assert stats["by_language"] == {}
    assert stats["average_duration_ms"] == 0
    assert stats["success_rate"] == 0


@pytest.mark.asyncio
async def test_aggregate_stats_completed_and_failed() -> None:
    """Stats reflect completed vs failed counts, success rate, and duration."""
    repo = ExecutionRepository(logger=_test_logger)
    user_id = str(uuid4())
    exec_ids: list[str] = []

    exec_ids.append(await _create_and_complete(repo, user_id, status=ExecutionStatus.COMPLETED))
    exec_ids.append(await _create_and_complete(repo, user_id, status=ExecutionStatus.COMPLETED))
    exec_ids.append(await _create_and_complete(repo, user_id, status=ExecutionStatus.FAILED))

    try:
        stats = await repo.aggregate_stats({"user_id": user_id})

        assert stats["total"] == 3
        assert stats["by_status"][ExecutionStatus.COMPLETED] == 2
        assert stats["by_status"][ExecutionStatus.FAILED] == 1
        assert stats["success_rate"] == pytest.approx(2 / 3)
        assert stats["average_duration_ms"] >= 0
        assert "python-3.11" in stats["by_language"]
        assert stats["by_language"]["python-3.11"] == 3
    finally:
        for eid in exec_ids:
            await repo.delete_execution(eid)


@pytest.mark.asyncio
async def test_aggregate_stats_no_completed() -> None:
    """When nothing completed, avg_duration is 0 and success_rate is 0."""
    repo = ExecutionRepository(logger=_test_logger)
    user_id = str(uuid4())

    eid = await _create_and_complete(repo, user_id, status=ExecutionStatus.FAILED)

    try:
        stats = await repo.aggregate_stats({"user_id": user_id})

        assert stats["total"] == 1
        assert stats["average_duration_ms"] == 0
        assert stats["success_rate"] == 0.0
    finally:
        await repo.delete_execution(eid)


@pytest.mark.asyncio
async def test_aggregate_stats_multiple_languages() -> None:
    """by_language groups by lang-lang_version correctly."""
    repo = ExecutionRepository(logger=_test_logger)
    user_id = str(uuid4())
    exec_ids: list[str] = []

    exec_ids.append(await _create_and_complete(repo, user_id, lang="python", lang_version="3.11"))
    exec_ids.append(await _create_and_complete(repo, user_id, lang="python", lang_version="3.12"))
    exec_ids.append(await _create_and_complete(repo, user_id, lang="python", lang_version="3.12"))

    try:
        stats = await repo.aggregate_stats({"user_id": user_id})

        assert stats["by_language"]["python-3.11"] == 1
        assert stats["by_language"]["python-3.12"] == 2
    finally:
        for eid in exec_ids:
            await repo.delete_execution(eid)
