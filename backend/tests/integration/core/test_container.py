import pytest
from app.core.database_context import Database
from app.services.event_service import EventService
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_container_resolves_services(scope: AsyncContainer) -> None:
    """Verify DI container resolves core services correctly."""
    db: Database = await scope.get(Database)
    assert db.name and isinstance(db.name, str)

    svc: EventService = await scope.get(EventService)
    assert isinstance(svc, EventService)
