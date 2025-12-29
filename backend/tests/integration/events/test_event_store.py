from datetime import datetime, timezone, timedelta
import logging

import pytest

from app.events.event_store import EventStore
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from app.core.database_context import Database

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.events.event_store")


@pytest.fixture()
async def event_store(scope) -> EventStore:  # type: ignore[valid-type]
    db: Database = await scope.get(Database)
    schema_registry: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    store = EventStore(db=db, schema_registry=schema_registry, logger=_test_logger)
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_store_and_query_events(event_store: EventStore) -> None:
    ev1 = PodCreatedEvent(
        execution_id="x1",
        pod_name="pod1",
        namespace="ns",
        metadata=AvroEventMetadata(service_name="svc", service_version="1", user_id="u1", correlation_id="cid"),
    )
    assert await event_store.store_event(ev1) is True

    ev2 = PodCreatedEvent(
        execution_id="x2",
        pod_name="pod2",
        namespace="ns",
        metadata=AvroEventMetadata(service_name="svc", service_version="1", user_id="u1"),
    )
    res = await event_store.store_batch([ev1, ev2])
    assert res["total"] == 2 and res["stored"] >= 1

    items = await event_store.get_events_by_type(ev1.event_type)
    assert any(getattr(e, "execution_id", None) == "x1" for e in items)
    exec_items = await event_store.get_execution_events("x1")
    assert any(getattr(e, "execution_id", None) == "x1" for e in exec_items)
    user_items = await event_store.get_user_events("u1")
    assert len(user_items) >= 2
    chain = await event_store.get_correlation_chain("cid")
    assert isinstance(chain, list)
    # Security types (may be empty)
    _ = await event_store.get_security_events()


@pytest.mark.asyncio
async def test_replay_events(event_store: EventStore) -> None:
    ev = UserLoggedInEvent(user_id="u1", login_method="password",
                           metadata=AvroEventMetadata(service_name="svc", service_version="1"))
    await event_store.store_event(ev)

    called = {"n": 0}

    async def cb(_):  # noqa: ANN001
        called["n"] += 1

    start = datetime.now(timezone.utc) - timedelta(days=1)
    cnt = await event_store.replay_events(start_time=start, callback=cb)
    assert cnt >= 1 and called["n"] >= 1
