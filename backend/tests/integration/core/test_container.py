import pytest
from dishka import AsyncContainer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.event_service import EventService

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_container_resolves_services(app_container, scope) -> None:  # type: ignore[valid-type]
    # Container is the real Dishka container
    assert isinstance(app_container, AsyncContainer)

    # Can resolve core dependencies from DI
    db: AsyncIOMotorDatabase = await scope.get(AsyncIOMotorDatabase)
    assert db.name and isinstance(db.name, str)

    svc: EventService = await scope.get(EventService)
    assert isinstance(svc, EventService)
