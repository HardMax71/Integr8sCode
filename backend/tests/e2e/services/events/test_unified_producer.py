import pytest

from app.db.repositories import EventRepository
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.events import UnifiedProducer
from app.settings import Settings

pytestmark = [pytest.mark.e2e]


async def test_publish_user_registered_event(
    unified_producer: UnifiedProducer, event_repository: EventRepository, test_settings: Settings
) -> None:

    event = UserRegisteredEvent(
        aggregate_id="u1",
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(
            service_name=test_settings.SERVICE_NAME,
            service_version=test_settings.SERVICE_VERSION,
            user_id="u1",
        ),
    )
    await unified_producer.produce(event_to_produce=event, key="u1")
    stored = await event_repository.get_event(event.event_id)
    assert stored is not None and stored.event_id == event.event_id
