import pytest
from dishka import AsyncContainer

from app.db.repositories import EventRepository
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.events import UnifiedProducer
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_publish_user_registered_event(scope: AsyncContainer) -> None:
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    repo: EventRepository = await scope.get(EventRepository)
    settings: Settings = await scope.get(Settings)

    event = UserRegisteredEvent(
        aggregate_id="u1",
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(
            service_name=settings.SERVICE_NAME,
            service_version=settings.SERVICE_VERSION,
            user_id="u1",
        ),
    )
    await producer.produce(event_to_produce=event, key="u1")
    stored = await repo.get_event(event.event_id)
    assert stored is not None and stored.event_id == event.event_id
