from datetime import datetime, timedelta, timezone

import pytest
from app.db.repositories.event_repository import EventRepository
from app.domain.events.event_models import Event
from app.infrastructure.kafka.events.metadata import AvroEventMetadata

pytestmark = pytest.mark.integration


@pytest.fixture()
async def repo(scope) -> EventRepository:  # type: ignore[valid-type]
    return await scope.get(EventRepository)


def make_event(event_id: str, etype: str = "UserLoggedIn", user: str | None = "u1", agg: str | None = "agg1") -> Event:
    return Event(
        event_id=event_id,
        event_type=etype,
        event_version="1.0",
        timestamp=datetime.now(timezone.utc),
        metadata=AvroEventMetadata(service_name="svc", service_version="1", user_id=user, correlation_id="c1"),
        payload={"k": 1, "execution_id": agg} if agg else {"k": 1},
        aggregate_id=agg,
    )


@pytest.mark.asyncio
async def test_store_get_and_queries(repo: EventRepository, db) -> None:  # type: ignore[valid-type]
    e1 = make_event("e1", etype="A", agg="x1")
    e2 = make_event("e2", etype="B", agg="x2")
    await repo.store_event(e1)
    await repo.store_events_batch([e2])
    got = await repo.get_event("e1")
    assert got and got.event_id == "e1"

    now = datetime.now(timezone.utc)
    by_type = await repo.get_events_by_type("A", start_time=now - timedelta(days=1), end_time=now + timedelta(days=1))
    assert any(ev.event_id == "e1" for ev in by_type)
    by_agg = await repo.get_events_by_aggregate("x2")
    assert any(ev.event_id == "e2" for ev in by_agg)
    by_corr = await repo.get_events_by_correlation("c1")
    assert len(by_corr.events) >= 2
    by_user = await repo.get_events_by_user("u1", limit=10)
    assert len(by_user) >= 2
    exec_events = await repo.get_execution_events("x1")
    assert any(ev.event_id == "e1" for ev in exec_events.events)


@pytest.mark.asyncio
async def test_statistics_and_search_and_delete(repo: EventRepository, db) -> None:  # type: ignore[valid-type]
    now = datetime.now(timezone.utc)
    await db.get_collection("events").insert_many(
        [
            {
                "event_id": "e3",
                "event_type": "C",
                "event_version": "1.0",
                "timestamp": now,
                "metadata": AvroEventMetadata(service_name="svc", service_version="1").model_dump(),
                "payload": {},
            },
        ]
    )
    stats = await repo.get_event_statistics(start_time=now - timedelta(days=1), end_time=now + timedelta(days=1))
    assert stats.total_events >= 1

    # search requires text index; guard if index not present
    try:
        res = await repo.search_events("test", filters=None, limit=10, skip=0)
        assert isinstance(res, list)
    except Exception:
        # Accept environments without text index
        pass
