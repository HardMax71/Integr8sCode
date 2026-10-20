from uuid import uuid4

import pytest

from app.db.docs import ExecutionDocument
from app.db.repositories import ExecutionRepository
from app.domain.enums import ExecutionErrorType, ExecutionStatus
from app.domain.execution import ExecutionResultDomain

pytestmark = pytest.mark.e2e


async def test_execution_crud_and_query(execution_repository: ExecutionRepository) -> None:
    user_id = str(uuid4())

    # Create
    created = ExecutionDocument(script="print('hello')", user_id=user_id)
    await execution_repository.create_execution(created)
    assert created.execution_id

    # Get
    got = await execution_repository.get_execution(created.execution_id)
    assert got and got.script.startswith("print") and got.status == ExecutionStatus.QUEUED

    # List
    items = await execution_repository.get_executions({"user_id": user_id}, limit=10, skip=0, sort=[("created_at", 1)])
    assert any(x.execution_id == created.execution_id for x in items)

    # Delete
    assert await execution_repository.delete_execution(created.execution_id) is True
    assert await execution_repository.get_execution(created.execution_id) is None


async def _create_and_complete(
    repo: ExecutionRepository,
    user_id: str,
    *,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    lang: str = "python",
    lang_version: str = "3.11",
) -> str:
    """Helper: create an execution then transition it to a terminal status."""
    created = ExecutionDocument(
        script="x = 1",
        lang=lang,
        lang_version=lang_version,
        user_id=user_id,
    )
    await repo.create_execution(created)
    wrote = await repo.write_terminal_result(
        ExecutionResultDomain(
            execution_id=created.execution_id,
            status=status,
            exit_code=0 if status == ExecutionStatus.COMPLETED else 1,
            stdout="ok",
            stderr="",
            error_type=ExecutionErrorType.SCRIPT_ERROR if status == ExecutionStatus.FAILED else None,
        )
    )
    assert wrote, f"write_terminal_result failed for {created.execution_id}"
    return created.execution_id


async def test_terminal_result_exists_only_once_the_execution_finished(
    execution_repository: ExecutionRepository,
) -> None:
    user_id = str(uuid4())
    queued = ExecutionDocument(script="x = 1", user_id=user_id)
    await execution_repository.create_execution(queued)
    finished_id = await _create_and_complete(execution_repository, user_id)

    assert await execution_repository.get_terminal_result(queued.execution_id) is None
    assert await execution_repository.get_terminal_result("missing-" + user_id) is None

    result = await execution_repository.get_terminal_result(finished_id)
    assert result is not None
    assert (result.status, result.exit_code, result.stdout, result.stderr) == (ExecutionStatus.COMPLETED, 0, "ok", "")


async def test_aggregate_stats_empty(execution_repository: ExecutionRepository) -> None:
    """Empty result set returns zero-value stats."""
    bogus_user = str(uuid4())

    stats = await execution_repository.aggregate_stats({"user_id": bogus_user})

    assert stats["total"] == 0
    assert stats["by_status"] == {}
    assert stats["by_language"] == {}
    assert stats["average_duration_ms"] == 0
    assert stats["success_rate"] == 0


async def test_aggregate_stats_completed_and_failed(execution_repository: ExecutionRepository) -> None:
    """Stats reflect completed vs failed counts, success rate, and duration."""
    user_id = str(uuid4())
    exec_ids: list[str] = []

    exec_ids.append(await _create_and_complete(execution_repository, user_id, status=ExecutionStatus.COMPLETED))
    exec_ids.append(await _create_and_complete(execution_repository, user_id, status=ExecutionStatus.COMPLETED))
    exec_ids.append(await _create_and_complete(execution_repository, user_id, status=ExecutionStatus.FAILED))

    try:
        stats = await execution_repository.aggregate_stats({"user_id": user_id})

        assert stats["total"] == 3
        assert stats["by_status"][ExecutionStatus.COMPLETED] == 2
        assert stats["by_status"][ExecutionStatus.FAILED] == 1
        assert stats["success_rate"] == pytest.approx(2 / 3)
        assert stats["average_duration_ms"] >= 0
        assert "python-3.11" in stats["by_language"]
        assert stats["by_language"]["python-3.11"] == 3
    finally:
        for eid in exec_ids:
            await execution_repository.delete_execution(eid)


async def test_aggregate_stats_no_completed(execution_repository: ExecutionRepository) -> None:
    """When nothing completed, avg_duration is 0 and success_rate is 0."""
    user_id = str(uuid4())

    eid = await _create_and_complete(execution_repository, user_id, status=ExecutionStatus.FAILED)

    try:
        stats = await execution_repository.aggregate_stats({"user_id": user_id})

        assert stats["total"] == 1
        assert stats["average_duration_ms"] == 0
        assert stats["success_rate"] == 0.0
    finally:
        await execution_repository.delete_execution(eid)


async def test_aggregate_stats_multiple_languages(execution_repository: ExecutionRepository) -> None:
    """by_language groups by lang-lang_version correctly."""
    user_id = str(uuid4())
    exec_ids: list[str] = []

    exec_ids.append(await _create_and_complete(execution_repository, user_id))
    exec_ids.append(await _create_and_complete(execution_repository, user_id, lang="python", lang_version="3.12"))
    exec_ids.append(await _create_and_complete(execution_repository, user_id, lang="python", lang_version="3.12"))

    try:
        stats = await execution_repository.aggregate_stats({"user_id": user_id})

        assert stats["by_language"]["python-3.11"] == 1
        assert stats["by_language"]["python-3.12"] == 2
    finally:
        for eid in exec_ids:
            await execution_repository.delete_execution(eid)


async def test_advance_status_moves_forward_only(execution_repository: ExecutionRepository) -> None:
    created = ExecutionDocument(script="x = 1", user_id=str(uuid4()))
    await execution_repository.create_execution(created)
    execution_id = created.execution_id

    assert await execution_repository.advance_status(execution_id, ExecutionStatus.RUNNING) is True
    assert await execution_repository.advance_status(execution_id, ExecutionStatus.SCHEDULED) is False
    got = await execution_repository.get_execution(execution_id)
    assert got is not None and got.status == ExecutionStatus.RUNNING

    await execution_repository.write_terminal_result(
        ExecutionResultDomain(
            execution_id=execution_id, status=ExecutionStatus.COMPLETED, exit_code=0, stdout="", stderr=""
        )
    )
    assert await execution_repository.advance_status(execution_id, ExecutionStatus.RUNNING) is False
    got = await execution_repository.get_execution(execution_id)
    assert got is not None and got.status == ExecutionStatus.COMPLETED
