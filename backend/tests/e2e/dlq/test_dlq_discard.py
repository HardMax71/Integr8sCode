import logging
import uuid
from datetime import datetime, timezone

import pytest
from app.db.docs import DLQMessageDocument
from app.db.repositories.dlq_repository import DLQRepository
from app.dlq.models import DLQMessageStatus
from app.domain.events.typed import ExecutionRequestedEvent
from dishka import AsyncContainer

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.dlq.discard")


async def _create_dlq_document(
    event_id: str | None = None,
    status: DLQMessageStatus = DLQMessageStatus.PENDING,
) -> DLQMessageDocument:
    """Helper to create a DLQ document directly in MongoDB."""
    if event_id is None:
        event_id = str(uuid.uuid4())

    event = make_execution_requested_event(execution_id=f"exec-{uuid.uuid4().hex[:8]}")
    # Override event_id for test predictability
    event_dict = event.model_dump()
    event_dict["event_id"] = event_id
    now = datetime.now(timezone.utc)

    doc = DLQMessageDocument(
        event=event_dict,
        original_topic=ExecutionRequestedEvent.topic(),
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
async def test_dlq_repository_marks_message_discarded(scope: AsyncContainer) -> None:
    """Test that DLQRepository.mark_message_discarded() updates status correctly."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a DLQ document
    event_id = f"dlq-discard-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.PENDING)

    # Discard the message
    reason = "max_retries_exceeded"
    result = await repository.mark_message_discarded(event_id, reason)

    assert result is True

    # Verify the status changed
    updated_doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
    assert updated_doc is not None
    assert updated_doc.status == DLQMessageStatus.DISCARDED
    assert updated_doc.discard_reason == reason
    assert updated_doc.discarded_at is not None


@pytest.mark.asyncio
async def test_dlq_discard_nonexistent_message_returns_false(scope: AsyncContainer) -> None:
    """Test that discarding a nonexistent message returns False."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Try to discard a message that doesn't exist
    result = await repository.mark_message_discarded(
        f"nonexistent-{uuid.uuid4().hex[:8]}",
        "test_reason",
    )

    assert result is False


@pytest.mark.asyncio
async def test_dlq_discard_sets_timestamp(scope: AsyncContainer) -> None:
    """Test that discarding sets the discarded_at timestamp."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a DLQ document
    event_id = f"dlq-ts-{uuid.uuid4().hex[:8]}"
    before_discard = datetime.now(timezone.utc)
    await _create_dlq_document(event_id=event_id)

    # Discard the message
    await repository.mark_message_discarded(event_id, "manual_discard")
    after_discard = datetime.now(timezone.utc)

    # Verify timestamp is set correctly
    doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
    assert doc is not None
    assert doc.discarded_at is not None
    assert before_discard <= doc.discarded_at <= after_discard


@pytest.mark.asyncio
async def test_dlq_discard_with_custom_reason(scope: AsyncContainer) -> None:
    """Test that custom discard reasons are stored."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a DLQ document
    event_id = f"dlq-reason-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id)

    # Discard with custom reason
    custom_reason = "manual: User requested deletion due to invalid payload"
    await repository.mark_message_discarded(event_id, custom_reason)

    # Verify the reason is stored
    doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
    assert doc is not None
    assert doc.discard_reason == custom_reason


@pytest.mark.asyncio
async def test_dlq_discard_from_scheduled_status(scope: AsyncContainer) -> None:
    """Test that scheduled messages can be discarded."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Create a SCHEDULED DLQ document
    event_id = f"dlq-scheduled-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.SCHEDULED)

    # Discard the message
    result = await repository.mark_message_discarded(event_id, "policy_change")

    assert result is True

    # Verify status transition
    doc = await DLQMessageDocument.find_one({"event.event_id": event_id})
    assert doc is not None
    assert doc.status == DLQMessageStatus.DISCARDED


@pytest.mark.asyncio
async def test_dlq_stats_reflect_discarded_messages(scope: AsyncContainer) -> None:
    """Test that DLQ statistics correctly count discarded messages."""
    repository: DLQRepository = await scope.get(DLQRepository)

    # Capture count before to ensure our discard is what increments the stat
    stats_before = await repository.get_dlq_stats()
    count_before = stats_before.by_status.get(DLQMessageStatus.DISCARDED, 0)

    # Create and discard a message
    event_id = f"dlq-stats-{uuid.uuid4().hex[:8]}"
    await _create_dlq_document(event_id=event_id, status=DLQMessageStatus.PENDING)
    await repository.mark_message_discarded(event_id, "test")

    # Get stats after - verify the count incremented by exactly 1
    stats_after = await repository.get_dlq_stats()
    count_after = stats_after.by_status.get(DLQMessageStatus.DISCARDED, 0)
    assert count_after == count_before + 1
