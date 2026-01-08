import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from app.db.repositories.event_repository import EventRepository
from app.domain.enums.events import EventType
from app.domain.events import Event
from app.domain.events.event_metadata import EventMetadata

_test_logger = logging.getLogger("test.db.repositories.event_repository")

pytestmark = pytest.mark.integration


def _make_event(
    event_id: str,
    event_type: EventType = EventType.EXECUTION_REQUESTED,
    aggregate_id: str | None = None,
    correlation_id: str = "corr-test",
    user_id: str | None = None,
    service_name: str = "test-service",
    timestamp: datetime | None = None,
) -> Event:
    """Factory for Event domain objects."""
    return Event(
        event_id=event_id,
        event_type=event_type,
        event_version="1.0",
        timestamp=timestamp or datetime.now(timezone.utc),
        metadata=EventMetadata(
            service_name=service_name,
            service_version="1.0.0",
            correlation_id=correlation_id,
            user_id=user_id,
        ),
        payload={"test": "data", "execution_id": aggregate_id},
        aggregate_id=aggregate_id,
    )


@pytest.mark.asyncio
async def test_store_and_get_event(unique_id: Callable[[str], str]) -> None:
    """Store event and retrieve by ID."""
    repo = EventRepository(logger=_test_logger)
    event_id = unique_id("evt-")
    event = _make_event(event_id=event_id)

    stored_id = await repo.store_event(event)
    assert stored_id == event_id

    retrieved = await repo.get_event(event_id)
    assert retrieved is not None
    assert retrieved.event_id == event_id
    assert retrieved.event_type == EventType.EXECUTION_REQUESTED


@pytest.mark.asyncio
async def test_get_event_not_found(unique_id: Callable[[str], str]) -> None:
    """Returns None for non-existent event."""
    repo = EventRepository(logger=_test_logger)
    result = await repo.get_event(unique_id("nonexistent-"))
    assert result is None


@pytest.mark.asyncio
async def test_get_events_by_aggregate(unique_id: Callable[[str], str]) -> None:
    """Retrieve events by aggregate_id."""
    repo = EventRepository(logger=_test_logger)
    aggregate_id = unique_id("exec-")

    # Store multiple events for same aggregate
    events = [
        _make_event(unique_id("evt-"), EventType.EXECUTION_REQUESTED, aggregate_id),
        _make_event(unique_id("evt-"), EventType.EXECUTION_QUEUED, aggregate_id),
        _make_event(unique_id("evt-"), EventType.EXECUTION_RUNNING, aggregate_id),
    ]
    for e in events:
        await repo.store_event(e)

    # Retrieve all
    result = await repo.get_events_by_aggregate(aggregate_id)
    assert len(result) >= 3

    # Filter by event type
    filtered = await repo.get_events_by_aggregate(
        aggregate_id, event_types=[EventType.EXECUTION_QUEUED]
    )
    assert all(e.event_type == EventType.EXECUTION_QUEUED for e in filtered)


@pytest.mark.asyncio
async def test_get_events_by_correlation(unique_id: Callable[[str], str]) -> None:
    """Retrieve events by correlation_id with pagination."""
    repo = EventRepository(logger=_test_logger)
    correlation_id = unique_id("corr-")

    # Store events with same correlation
    for i in range(5):
        event = _make_event(
            unique_id("evt-"),
            correlation_id=correlation_id,
            aggregate_id=unique_id("exec-"),
        )
        await repo.store_event(event)

    result = await repo.get_events_by_correlation(correlation_id, limit=3, skip=0)
    assert result.total >= 5
    assert len(result.events) == 3
    assert result.has_more is True

    # Get second page
    page2 = await repo.get_events_by_correlation(correlation_id, limit=3, skip=3)
    assert len(page2.events) >= 2


@pytest.mark.asyncio
async def test_get_execution_events(unique_id: Callable[[str], str]) -> None:
    """Retrieve events for an execution with system event filtering."""
    repo = EventRepository(logger=_test_logger)
    execution_id = unique_id("exec-")

    # Store regular and system events
    await repo.store_event(
        _make_event(unique_id("evt-"), aggregate_id=execution_id, service_name="api")
    )
    await repo.store_event(
        _make_event(unique_id("evt-"), aggregate_id=execution_id, service_name="system-monitor")
    )

    # Without filter
    all_events = await repo.get_execution_events(execution_id, exclude_system_events=False)
    assert all_events.total >= 2

    # With filter
    filtered = await repo.get_execution_events(execution_id, exclude_system_events=True)
    assert all(not e.metadata.service_name.startswith("system-") for e in filtered.events)


@pytest.mark.asyncio
async def test_get_event_statistics(unique_id: Callable[[str], str]) -> None:
    """Get aggregated statistics for events."""
    repo = EventRepository(logger=_test_logger)
    now = datetime.now(timezone.utc)

    # Store events of different types
    for event_type in [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_COMPLETED]:
        for _ in range(2):
            event = _make_event(unique_id("evt-"), event_type, timestamp=now)
            await repo.store_event(event)

    stats = await repo.get_event_statistics(
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=1),
    )

    assert stats.total_events > 0
    assert isinstance(stats.events_by_type, dict)
    assert isinstance(stats.events_by_service, dict)


@pytest.mark.asyncio
async def test_get_user_events_paginated(unique_id: Callable[[str], str]) -> None:
    """Retrieve user's events with pagination and filtering."""
    repo = EventRepository(logger=_test_logger)
    user_id = unique_id("user-")

    # Store events for user
    for i in range(3):
        event = _make_event(
            unique_id("evt-"),
            event_type=EventType.EXECUTION_REQUESTED if i % 2 == 0 else EventType.EXECUTION_COMPLETED,
            user_id=user_id,
        )
        await repo.store_event(event)

    # Get all user events
    result = await repo.get_user_events_paginated(user_id, limit=10)
    assert result.total == 3

    # Filter by event type (i=0,2 are EXECUTION_REQUESTED, i=1 is EXECUTION_COMPLETED)
    filtered = await repo.get_user_events_paginated(
        user_id,
        event_types=[EventType.EXECUTION_REQUESTED.value],
        limit=10,
    )
    assert filtered.total == 2
    assert all(e.event_type == EventType.EXECUTION_REQUESTED for e in filtered.events)


@pytest.mark.asyncio
async def test_query_events_with_filter(unique_id: Callable[[str], str]) -> None:
    """Query events with arbitrary filter."""
    repo = EventRepository(logger=_test_logger)
    service_name = unique_id("svc-")

    # Store events
    for _ in range(3):
        event = _make_event(unique_id("evt-"), service_name=service_name)
        await repo.store_event(event)

    result = await repo.query_events(
        query={"metadata.service_name": service_name},
        limit=10,
    )
    assert result.total >= 3
    assert all(e.metadata.service_name == service_name for e in result.events)


@pytest.mark.asyncio
async def test_aggregate_events(unique_id: Callable[[str], str]) -> None:
    """Run aggregation pipeline on events."""
    repo = EventRepository(logger=_test_logger)
    service_name = unique_id("svc-")

    # Store events
    for _ in range(3):
        await repo.store_event(_make_event(unique_id("evt-"), service_name=service_name))

    pipeline: list[dict[str, Any]] = [
        {"$match": {"metadata.service_name": service_name}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
    ]
    result = await repo.aggregate_events(pipeline, limit=100)
    assert len(result.results) > 0


@pytest.mark.asyncio
async def test_list_event_types(unique_id: Callable[[str], str]) -> None:
    """List distinct event types."""
    repo = EventRepository(logger=_test_logger)
    service_name = unique_id("svc-")

    # Store events of different types
    await repo.store_event(
        _make_event(unique_id("evt-"), EventType.EXECUTION_REQUESTED, service_name=service_name)
    )
    await repo.store_event(
        _make_event(unique_id("evt-"), EventType.EXECUTION_COMPLETED, service_name=service_name)
    )

    types = await repo.list_event_types(match={"metadata.service_name": service_name})
    assert len(types) >= 2


@pytest.mark.asyncio
async def test_delete_event_with_archival(unique_id: Callable[[str], str]) -> None:
    """Delete event with archival."""
    repo = EventRepository(logger=_test_logger)
    event_id = unique_id("evt-")
    event = _make_event(event_id)

    await repo.store_event(event)

    archived = await repo.delete_event_with_archival(
        event_id, deleted_by="admin", deletion_reason="Test cleanup"
    )
    assert archived is not None
    assert archived.event_id == event_id
    assert archived.deleted_by == "admin"

    # Original should be gone
    assert await repo.get_event(event_id) is None


@pytest.mark.asyncio
async def test_delete_nonexistent_event(unique_id: Callable[[str], str]) -> None:
    """Returns None when deleting non-existent event."""
    repo = EventRepository(logger=_test_logger)
    result = await repo.delete_event_with_archival(
        unique_id("nonexistent-"), "admin", "test"
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_aggregate_replay_info(unique_id: Callable[[str], str]) -> None:
    """Get replay info for an aggregate."""
    repo = EventRepository(logger=_test_logger)
    aggregate_id = unique_id("exec-")

    # Store events with timestamps
    base_time = datetime.now(timezone.utc)
    for i, event_type in enumerate(
        [EventType.EXECUTION_REQUESTED, EventType.EXECUTION_QUEUED, EventType.EXECUTION_COMPLETED]
    ):
        event = _make_event(
            unique_id("evt-"),
            event_type,
            aggregate_id,
            timestamp=base_time + timedelta(seconds=i),
        )
        await repo.store_event(event)

    info = await repo.get_aggregate_replay_info(aggregate_id)
    assert info is not None
    assert info.event_count >= 3
    assert len(info.event_types) >= 3
    assert info.start_time <= info.end_time


@pytest.mark.asyncio
async def test_get_aggregate_replay_info_not_found(unique_id: Callable[[str], str]) -> None:
    """Returns None for non-existent aggregate."""
    repo = EventRepository(logger=_test_logger)
    result = await repo.get_aggregate_replay_info(unique_id("nonexistent-"))
    assert result is None
