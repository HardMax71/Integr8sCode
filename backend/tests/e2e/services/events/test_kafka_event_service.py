import pytest
from app.db.repositories import EventRepository
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.services.kafka_event_service import KafkaEventService
from app.settings import Settings
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.kafka, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_publish_user_registered_event(scope: AsyncContainer) -> None:
    svc: KafkaEventService = await scope.get(KafkaEventService)
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
    event_id = await svc.publish_event(event, key="u1")
    assert isinstance(event_id, str) and event_id
    stored = await repo.get_event(event_id)
    assert stored is not None and stored.event_id == event_id
