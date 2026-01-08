import logging
from collections.abc import Callable

import backoff
import pytest
from app.core.database_context import Database
from app.domain.enums.auth import LoginMethod
from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events.metadata import AvroEventMetadata
from app.infrastructure.kafka.events.user import UserLoggedInEvent
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.mongodb]

_test_logger = logging.getLogger("test.events.event_store_consumer")


@pytest.mark.asyncio
async def test_event_store_consumer_stores_events(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    """Test that the app's EventStoreConsumer (started in lifespan) stores events to MongoDB.

    The EventStoreConsumer is started automatically by the app lifespan and subscribes
    to all topics. We just need to publish an event and verify it appears in MongoDB.
    """
    # Resolve DI - producer is already running, EventStoreConsumer is already running via app lifespan
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    db: Database = await scope.get(Database)

    # Build an event
    ev = UserLoggedInEvent(
        user_id=unique_id("u-"),
        login_method=LoginMethod.PASSWORD,
        metadata=AvroEventMetadata(service_name="tests", service_version="1.0.0"),
    )

    # Publish the event - the app's EventStoreConsumer will pick it up
    await producer.produce(ev, key=ev.metadata.user_id or "u")

    # Wait until the event is persisted in Mongo by the app's EventStoreConsumer
    coll = db.get_collection("events")

    @backoff.on_exception(backoff.constant, AssertionError, max_time=30.0, interval=0.3)
    async def _wait_exists() -> None:
        doc = await coll.find_one({"event_id": ev.event_id})
        assert doc is not None, f"Event {ev.event_id} not found in MongoDB"

    await _wait_exists()
