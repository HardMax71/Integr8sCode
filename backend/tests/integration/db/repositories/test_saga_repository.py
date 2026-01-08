import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums.saga import SagaState
from app.domain.saga import Saga, SagaFilter

_test_logger = logging.getLogger("test.db.repositories.saga_repository")

pytestmark = pytest.mark.integration


def _make_saga(
    saga_id: str,
    saga_name: str = "execution_saga",
    execution_id: str | None = None,
    state: SagaState = SagaState.RUNNING,
    user_id: str | None = None,
    error_message: str | None = None,
) -> Saga:
    """Factory for Saga domain objects."""
    return Saga(
        saga_id=saga_id,
        saga_name=saga_name,
        execution_id=execution_id or saga_id.replace("saga-", "exec-"),
        state=state,
        completed_steps=[],
        context_data={"user_id": user_id} if user_id else {},
        error_message=error_message,
    )


@pytest.mark.asyncio
async def test_upsert_and_get_saga(unique_id: Callable[[str], str]) -> None:
    """Create saga and retrieve by ID."""
    repo = SagaRepository()
    saga_id = unique_id("saga-")
    saga = _make_saga(saga_id)

    # Insert (upsert returns False for new)
    is_update = await repo.upsert_saga(saga)
    assert is_update is False

    # Get
    retrieved = await repo.get_saga(saga_id)
    assert retrieved is not None
    assert retrieved.saga_id == saga_id
    assert retrieved.state == SagaState.RUNNING


@pytest.mark.asyncio
async def test_upsert_existing_saga(unique_id: Callable[[str], str]) -> None:
    """Update existing saga via upsert."""
    repo = SagaRepository()
    saga_id = unique_id("saga-")
    saga = _make_saga(saga_id)

    await repo.upsert_saga(saga)

    # Update state
    saga.state = SagaState.COMPLETED
    saga.completed_steps = ["step1", "step2"]
    is_update = await repo.upsert_saga(saga)
    assert is_update is True

    # Verify
    retrieved = await repo.get_saga(saga_id)
    assert retrieved is not None
    assert retrieved.state == SagaState.COMPLETED
    assert len(retrieved.completed_steps) == 2


@pytest.mark.asyncio
async def test_get_saga_not_found(unique_id: Callable[[str], str]) -> None:
    """Returns None for non-existent saga."""
    repo = SagaRepository()
    result = await repo.get_saga(unique_id("nonexistent-"))
    assert result is None


@pytest.mark.asyncio
async def test_get_saga_by_execution_and_name(unique_id: Callable[[str], str]) -> None:
    """Retrieve saga by execution_id and saga_name."""
    repo = SagaRepository()
    saga_id = unique_id("saga-")
    execution_id = unique_id("exec-")
    saga_name = "test_saga"

    saga = _make_saga(saga_id, saga_name=saga_name, execution_id=execution_id)
    await repo.upsert_saga(saga)

    retrieved = await repo.get_saga_by_execution_and_name(execution_id, saga_name)
    assert retrieved is not None
    assert retrieved.saga_id == saga_id


@pytest.mark.asyncio
async def test_get_sagas_by_execution(unique_id: Callable[[str], str]) -> None:
    """Retrieve sagas by execution_id with state filtering."""
    repo = SagaRepository()
    execution_id = unique_id("exec-")

    # Create sagas with different states
    await repo.upsert_saga(_make_saga(unique_id("saga-"), execution_id=execution_id, state=SagaState.RUNNING))
    await repo.upsert_saga(_make_saga(unique_id("saga-"), execution_id=execution_id, state=SagaState.COMPLETED))
    await repo.upsert_saga(_make_saga(unique_id("saga-"), execution_id=execution_id, state=SagaState.RUNNING))

    # Get all
    result = await repo.get_sagas_by_execution(execution_id)
    assert result.total >= 3

    # Filter by state
    running = await repo.get_sagas_by_execution(execution_id, state=SagaState.RUNNING)
    assert running.total >= 2


@pytest.mark.asyncio
async def test_list_sagas_with_filter(unique_id: Callable[[str], str]) -> None:
    """List sagas with SagaFilter."""
    repo = SagaRepository()
    user_id = unique_id("user-")
    saga_name = "filter_test_saga"

    # Create sagas
    for state in [SagaState.RUNNING, SagaState.COMPLETED, SagaState.FAILED]:
        saga = _make_saga(
            unique_id("saga-"),
            saga_name=saga_name,
            user_id=user_id,
            state=state,
            error_message="Test error" if state == SagaState.FAILED else None,
        )
        await repo.upsert_saga(saga)

    # Filter by user_id
    user_filter = SagaFilter(user_id=user_id)
    result = await repo.list_sagas(user_filter)
    assert result.total >= 3

    # Filter by state
    state_filter = SagaFilter(state=SagaState.COMPLETED)
    completed = await repo.list_sagas(state_filter)
    assert all(s.state == SagaState.COMPLETED for s in completed.sagas)

    # Filter by saga_name
    name_filter = SagaFilter(saga_name=saga_name)
    named = await repo.list_sagas(name_filter)
    assert all(s.saga_name == saga_name for s in named.sagas)

    # Filter by error_status
    error_filter = SagaFilter(error_status=True)
    with_errors = await repo.list_sagas(error_filter)
    assert all(s.error_message is not None for s in with_errors.sagas)


@pytest.mark.asyncio
async def test_list_sagas_pagination(unique_id: Callable[[str], str]) -> None:
    """List sagas with pagination."""
    repo = SagaRepository()
    user_id = unique_id("user-")

    # Create multiple sagas
    for _ in range(5):
        await repo.upsert_saga(_make_saga(unique_id("saga-"), user_id=user_id))

    user_filter = SagaFilter(user_id=user_id)

    # First page
    page1 = await repo.list_sagas(user_filter, limit=2, skip=0)
    assert len(page1.sagas) == 2
    assert page1.total >= 5

    # Second page
    page2 = await repo.list_sagas(user_filter, limit=2, skip=2)
    assert len(page2.sagas) == 2


@pytest.mark.asyncio
async def test_update_saga_state(unique_id: Callable[[str], str]) -> None:
    """Update saga state."""
    repo = SagaRepository()
    saga_id = unique_id("saga-")
    saga = _make_saga(saga_id)
    await repo.upsert_saga(saga)

    # Update state
    success = await repo.update_saga_state(saga_id, SagaState.COMPLETED)
    assert success is True

    retrieved = await repo.get_saga(saga_id)
    assert retrieved is not None
    assert retrieved.state == SagaState.COMPLETED


@pytest.mark.asyncio
async def test_update_saga_state_with_error(unique_id: Callable[[str], str]) -> None:
    """Update saga state with error message."""
    repo = SagaRepository()
    saga_id = unique_id("saga-")
    saga = _make_saga(saga_id)
    await repo.upsert_saga(saga)

    success = await repo.update_saga_state(saga_id, SagaState.FAILED, "Step 2 failed: timeout")
    assert success is True

    retrieved = await repo.get_saga(saga_id)
    assert retrieved is not None
    assert retrieved.state == SagaState.FAILED
    assert retrieved.error_message == "Step 2 failed: timeout"


@pytest.mark.asyncio
async def test_update_saga_state_not_found(unique_id: Callable[[str], str]) -> None:
    """Update returns False for non-existent saga."""
    repo = SagaRepository()
    result = await repo.update_saga_state(unique_id("nonexistent-"), SagaState.COMPLETED)
    assert result is False


@pytest.mark.asyncio
async def test_count_sagas_by_state(unique_id: Callable[[str], str]) -> None:
    """Count sagas grouped by state."""
    repo = SagaRepository()

    # Create sagas in different states
    for state in [SagaState.RUNNING, SagaState.COMPLETED, SagaState.FAILED]:
        await repo.upsert_saga(_make_saga(unique_id("saga-"), state=state))

    counts = await repo.count_sagas_by_state()
    assert isinstance(counts, dict)
    # Should have entries for the states we created
    assert len(counts) > 0


@pytest.mark.asyncio
async def test_find_timed_out_sagas(unique_id: Callable[[str], str]) -> None:
    """Find sagas that have timed out."""
    repo = SagaRepository()

    # Create running saga with old timestamp
    saga = _make_saga(unique_id("saga-"), state=SagaState.RUNNING)
    saga.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await repo.upsert_saga(saga)

    # Find timed out
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    timed_out = await repo.find_timed_out_sagas(cutoff)
    assert len(timed_out) >= 1
    assert all(s.created_at < cutoff for s in timed_out)


@pytest.mark.asyncio
async def test_get_saga_statistics(unique_id: Callable[[str], str]) -> None:
    """Get saga statistics."""
    repo = SagaRepository()
    user_id = unique_id("user-")

    # Create sagas
    for state in [SagaState.RUNNING, SagaState.COMPLETED]:
        saga = _make_saga(unique_id("saga-"), state=state, user_id=user_id)
        if state == SagaState.COMPLETED:
            saga.completed_at = datetime.now(timezone.utc)
        await repo.upsert_saga(saga)

    # Get stats with filter
    saga_filter = SagaFilter(user_id=user_id)
    stats = await repo.get_saga_statistics(saga_filter)

    assert "total" in stats
    assert "by_state" in stats
    assert "average_duration_seconds" in stats
    assert stats["total"] >= 2
