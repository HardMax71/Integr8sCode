import pytest
from app.services.event_service import EventService
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_container_resolves_services(app_container: AsyncContainer, scope: AsyncContainer) -> None:
    assert isinstance(app_container, AsyncContainer)

    svc: EventService = await scope.get(EventService)
    assert isinstance(svc, EventService)
