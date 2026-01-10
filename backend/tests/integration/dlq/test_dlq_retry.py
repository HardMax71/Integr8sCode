import logging
import uuid
from datetime import datetime, timezone

import pytest
from app.db.docs import DLQMessageDocument
from app.db.repositories.dlq_repository import DLQRepository
from app.dlq.models import DLQMessageStatus
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.dlq.retry")


async def _create_dlq_document(
    event_id: str | None = None,
    status: DLQMessageStatus = DLQMessageStatus.PENDING,
) -> DLQMessageDocument:
    """Helper to create a DLQ document directly in MongoDB."""
    if event_id is None:
        event_id = str(uuid.uuid4())

    event = make_execution_requested_event(execution_id=f"exec-{uuid.uuid4().hex[:8]}")
    now = datetime.now(timezone.utc)

    doc = DLQMessageDocument(
        event=event.model_dump(),
        event_id=event_id,
        event_type=EventType.EXECUTION_REQUESTED,
        original_topic=str(KafkaTopic.EXECUTION_EVENTS),
        error="Test error",
        retry_count=0,
        failed_at=now,
        status=status,
        producer_id="test-producer",
        created_at=now,
    )
    await doc.insert()
    return doc


@pytest.mark.asyncio
async def test_dlq_repository_marks_message_retried(scope: AsyncContainer) -> None:
    """Test that DLQRepository.mark_message_retried() updates status correctly."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a DLQ document
    event_id = f"dlq-retry-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.SCHEDULED)

    # Mark as retried
    result = await repository.mark_message_retried(event_id)

    assert result is True

    # Verify the status changed
    updated_doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert updated_doc is not None
    assert updated_doc.status == DLQMessageStatus.RETRIED
    assert updated_doc.retried_at is not None


@pytest.mark.asyncio
async def test_dlq_retry_nonexistent_message_returns_false(scope: AsyncContainer) -> None:
    """Test that retrying a nonexistent message returns False."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Try to retry a message that doesn't exist
    result = await repository.mark_message_retried(f"nonexistent-{uuid.uuid4().hex[:8]}")

    assert result is False


@pytest.mark.asyncio
async def test_dlq_retry_sets_timestamp(scope: AsyncContainer) -> None:
    """Test that retrying sets the retried_at timestamp."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a DLQ document
    event_id = f"dlq-retry-ts-{uuid.uuid4().hex[:8]}"
    before_retry = datetime.now(timezone.utc)
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.SCHEDULED)

    # Retry the message
    await repository.mark_message_retried(event_id)
    after_retry = datetime.now(timezone.utc)

    # Verify timestamp is set correctly
    doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert doc is not None
    assert doc.retried_at is not None
    assert before_retry <= doc.retried_at <= after_retry


@pytest.mark.asyncio
async def test_dlq_retry_from_pending_status(scope: AsyncContainer) -> None:
    """Test that pending messages can be retried."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a PENDING DLQ document
    event_id = f"dlq-pending-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.PENDING)

    # Retry the message
    result = await repository.mark_message_retried(event_id)

    assert result is True

    # Verify status transition
    doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert doc is not None
    assert doc.status == DLQMessageStatus.RETRIED


@pytest.mark.asyncio
async def test_dlq_stats_reflect_retried_messages(scope: AsyncContainer) -> None:
    """Test that DLQ statistics correctly count retried messages."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Capture count before to ensure our retry is what increments the stat
    stats_before = await repository.get_dlq_stats()
    count_before = stats_before.by_status.get(DLQMessageStatus.RETRIED.value, 0)

    # Create and retry a message
    event_id = f"dlq-stats-retry-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.SCHEDULED)
    await repository.mark_message_retried(event_id)

    # Get stats after - verify the count incremented by exactly 1
    stats_after = await repository.get_dlq_stats()
    count_after = stats_after.by_status.get(DLQMessageStatus.RETRIED.value, 0)
    assert count_after == count_before + 1


@pytest.mark.asyncio
async def test_dlq_retry_already_retried_message(scope: AsyncContainer) -> None:
    """Test that retrying an already RETRIED message still succeeds at repository level.

    Note: The DLQManager.retry_message_manually guards against this, but the
    repository method doesn't - it's a low-level operation that always succeeds.
    """
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create an already RETRIED document
    event_id = f"dlq-already-retried-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.RETRIED)

    # Repository method still succeeds (no guard at this level)
    result = await repository.mark_message_retried(event_id)
    assert result is True

    # Status remains RETRIED
    doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert doc is not None
    assert doc.status == DLQMessageStatus.RETRIED


@pytest.mark.asyncio
async def test_dlq_retry_discarded_message(scope: AsyncContainer) -> None:
    """Test that retrying a DISCARDED message still succeeds at repository level.

    Note: The DLQManager.retry_message_manually guards against this and returns False,
    but the repository method is a low-level operation that doesn't validate transitions.
    """
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a DISCARDED document
    event_id = f"dlq-discarded-retry-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.DISCARDED)

    # Repository method succeeds (transitions status back to RETRIED)
    result = await repository.mark_message_retried(event_id)
    assert result is True

    # Status is now RETRIED (repository doesn't guard transitions)
    doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert doc is not None
    assert doc.status == DLQMessageStatus.RETRIED


@pytest.mark.asyncio
async def test_dlq_discard_already_discarded_message(scope: AsyncContainer) -> None:
    """Test that discarding an already DISCARDED message updates the reason."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create an already DISCARDED document
    event_id = f"dlq-already-discarded-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.DISCARDED)

    # Discard again with a new reason
    new_reason = "updated_discard_reason"
    result = await repository.mark_message_discarded(event_id, new_reason)
    assert result is True

    # Reason is updated
    doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert doc is not None
    assert doc.status == DLQMessageStatus.DISCARDED
    assert doc.discard_reason == new_reason


@pytest.mark.asyncio
async def test_dlq_discard_retried_message(scope: AsyncContainer) -> None:
    """Test that discarding a RETRIED message transitions to DISCARDED."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a RETRIED document
    event_id = f"dlq-retried-discard-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.RETRIED)

    # Discard it
    reason = "manual_cleanup"
    result = await repository.mark_message_discarded(event_id, reason)
    assert result is True

    # Status is now DISCARDED
    doc = await DLQMessageDocument.find_one({"event_id": event_id})
    assert doc is not None
    assert doc.status == DLQMessageStatus.DISCARDED
    assert doc.discard_reason == reason
