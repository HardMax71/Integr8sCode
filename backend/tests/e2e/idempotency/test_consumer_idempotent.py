import uuid

import pytest
from app.domain.idempotency import IdempotencyStatus, KeyStrategy
from app.services.idempotency import IdempotencyManager
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.redis]


@pytest.mark.asyncio
async def test_idempotency_manager_blocks_duplicates(scope: AsyncContainer) -> None:
    """Test that IdempotencyManager blocks duplicate events.

    This tests the core idempotency behavior directly without Kafka:
    1. First check_and_reserve() returns is_duplicate=False (key reserved)
    2. Second check_and_reserve() returns is_duplicate=True (duplicate blocked)
    """
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    execution_id = f"e-{uuid.uuid4().hex[:8]}"
    event = make_execution_requested_event(execution_id=execution_id)

    # First call: should reserve the key (not a duplicate)
    result1 = await idm.check_and_reserve(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert result1.is_duplicate is False
    assert result1.status == IdempotencyStatus.PROCESSING

    # Second call with same event: should be blocked (is a duplicate)
    result2 = await idm.check_and_reserve(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert result2.is_duplicate is True
    assert result2.status == IdempotencyStatus.PROCESSING


@pytest.mark.asyncio
async def test_idempotency_manager_allows_different_events(scope: AsyncContainer) -> None:
    """Test that different events are processed independently."""
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    event1 = make_execution_requested_event(execution_id=f"e-{uuid.uuid4().hex[:8]}")
    event2 = make_execution_requested_event(execution_id=f"e-{uuid.uuid4().hex[:8]}")

    result1 = await idm.check_and_reserve(event1, key_strategy=KeyStrategy.EVENT_BASED)
    result2 = await idm.check_and_reserve(event2, key_strategy=KeyStrategy.EVENT_BASED)

    # Both should be allowed (different events)
    assert result1.is_duplicate is False
    assert result2.is_duplicate is False


@pytest.mark.asyncio
async def test_idempotency_manager_mark_completed(scope: AsyncContainer) -> None:
    """Test marking an event as completed."""
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    event = make_execution_requested_event(execution_id=f"e-{uuid.uuid4().hex[:8]}")

    # Reserve the key
    result = await idm.check_and_reserve(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert result.is_duplicate is False

    # Mark as completed
    marked = await idm.mark_completed(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert marked is True

    # Check again - should still be duplicate but now COMPLETED status
    result2 = await idm.check_and_reserve(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert result2.is_duplicate is True
    assert result2.status == IdempotencyStatus.COMPLETED


@pytest.mark.asyncio
async def test_idempotency_manager_mark_failed(scope: AsyncContainer) -> None:
    """Test marking an event as failed."""
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    event = make_execution_requested_event(execution_id=f"e-{uuid.uuid4().hex[:8]}")

    # Reserve the key
    result = await idm.check_and_reserve(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert result.is_duplicate is False

    # Mark as failed
    marked = await idm.mark_failed(event, error="test error", key_strategy=KeyStrategy.EVENT_BASED)
    assert marked is True

    # Check again - should be duplicate with FAILED status
    result2 = await idm.check_and_reserve(event, key_strategy=KeyStrategy.EVENT_BASED)
    assert result2.is_duplicate is True
    assert result2.status == IdempotencyStatus.FAILED


@pytest.mark.asyncio
async def test_idempotency_content_hash_strategy(scope: AsyncContainer) -> None:
    """Test content hash strategy blocks events with same content but different IDs."""
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    execution_id = f"e-{uuid.uuid4().hex[:8]}"
    # Two events with different event_ids but same content
    event1 = make_execution_requested_event(execution_id=execution_id)
    event2 = make_execution_requested_event(execution_id=execution_id)

    # With CONTENT_HASH strategy, same content = duplicate
    result1 = await idm.check_and_reserve(event1, key_strategy=KeyStrategy.CONTENT_HASH)
    result2 = await idm.check_and_reserve(event2, key_strategy=KeyStrategy.CONTENT_HASH)

    assert result1.is_duplicate is False
    assert result2.is_duplicate is True  # Same content = blocked
