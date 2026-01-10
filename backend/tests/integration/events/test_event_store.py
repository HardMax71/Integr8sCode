import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from dishka import AsyncContainer

from app.db.docs import EventDocument
from app.domain.enums.events import EventType
from app.events.event_store import EventStore
from app.infrastructure.kafka.events.base import BaseEvent
from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.events.event_store")


@pytest.mark.asyncio
async def test_event_store_stores_single_event(scope: AsyncContainer) -> None:
    """Test that EventStore.store_event() persists an event to MongoDB."""
    store: EventStore = await scope.get(EventStore)

    # Create a unique event
    execution_id = f"exec-{uuid.uuid4().hex[:8]}"
    event = make_execution_requested_event(execution_id=execution_id)

    # Store the event
    result = await store.store_event(event)
    assert result is True

    # Verify it's in MongoDB
    doc = await EventDocument.find_one({"event_id": event.event_id})
    assert doc is not None
    assert doc.event_id == event.event_id
    assert doc.event_type == EventType.EXECUTION_REQUESTED
    assert doc.aggregate_id == execution_id
    assert doc.stored_at is not None
    assert doc.ttl_expires_at is not None
    # TTL should be ~90 days in the future
    assert doc.ttl_expires_at > datetime.now(timezone.utc) + timedelta(days=89)


@pytest.mark.asyncio
async def test_event_store_stores_batch(scope: AsyncContainer) -> None:
    """Test that EventStore.store_batch() persists multiple events."""
    store: EventStore = await scope.get(EventStore)

    # Create multiple unique events
    events: list[BaseEvent] = [
        make_execution_requested_event(execution_id=f"exec-batch-{uuid.uuid4().hex[:8]}")
        for _ in range(5)
    ]

    # Store the batch
    results = await store.store_batch(events)

    assert results["total"] == 5
    assert results["stored"] == 5
    assert results["duplicates"] == 0
    assert results["failed"] == 0

    # Verify all events are in MongoDB
    for event in events:
        doc = await EventDocument.find_one({"event_id": event.event_id})
        assert doc is not None
        assert doc.event_type == EventType.EXECUTION_REQUESTED


@pytest.mark.asyncio
async def test_event_store_handles_duplicates(scope: AsyncContainer) -> None:
    """Test that EventStore handles duplicate event IDs gracefully."""
    store: EventStore = await scope.get(EventStore)

    # Create an event
    event = make_execution_requested_event(execution_id=f"exec-dup-{uuid.uuid4().hex[:8]}")

    # Store it twice
    result1 = await store.store_event(event)
    result2 = await store.store_event(event)

    # Both should succeed (second is a no-op due to duplicate handling)
    assert result1 is True
    assert result2 is True

    # Only one document should exist
    count = await EventDocument.find({"event_id": event.event_id}).count()
    assert count == 1


@pytest.mark.asyncio
async def test_event_store_batch_handles_duplicates(scope: AsyncContainer) -> None:
    """Test that store_batch handles duplicates within the batch."""
    store: EventStore = await scope.get(EventStore)

    # Create an event and store it first
    event = make_execution_requested_event(execution_id=f"exec-batch-dup-{uuid.uuid4().hex[:8]}")
    await store.store_event(event)

    # Create a batch with one new event and one duplicate
    new_event = make_execution_requested_event(execution_id=f"exec-batch-new-{uuid.uuid4().hex[:8]}")
    batch: list[BaseEvent] = [new_event, event]  # event is already stored

    results = await store.store_batch(batch)

    assert results["total"] == 2
    assert results["stored"] == 1  # Only the new one
    assert results["duplicates"] == 1  # The duplicate


@pytest.mark.asyncio
async def test_event_store_retrieves_by_id(scope: AsyncContainer) -> None:
    """Test that EventStore.get_event() retrieves a stored event."""
    store: EventStore = await scope.get(EventStore)

    # Create and store an event
    execution_id = f"exec-get-{uuid.uuid4().hex[:8]}"
    event = make_execution_requested_event(execution_id=execution_id, script="print('test')")
    await store.store_event(event)

    # Retrieve it
    retrieved = await store.get_event(event.event_id)

    assert retrieved is not None
    assert retrieved.event_id == event.event_id
    assert retrieved.event_type == EventType.EXECUTION_REQUESTED


@pytest.mark.asyncio
async def test_event_store_retrieves_by_type(scope: AsyncContainer) -> None:
    """Test that EventStore.get_events_by_type() works correctly."""
    store: EventStore = await scope.get(EventStore)

    # Store a few events
    unique_prefix = uuid.uuid4().hex[:8]
    events: list[BaseEvent] = [
        make_execution_requested_event(execution_id=f"exec-type-{unique_prefix}-{i}")
        for i in range(3)
    ]
    await store.store_batch(events)

    # Query by type
    retrieved = await store.get_events_by_type(
        EventType.EXECUTION_REQUESTED,
        limit=100,
    )

    # Should find at least our 3 events
    assert len(retrieved) >= 3

    # All should be EXECUTION_REQUESTED
    for ev in retrieved:
        assert ev.event_type == EventType.EXECUTION_REQUESTED
