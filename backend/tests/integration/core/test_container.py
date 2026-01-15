# mypy: disable-error-code="slop-isinstance"
# Rationale: Test assertions validating API contract types
import pytest
from app.core.database_context import Database
from app.services.event_service import EventService
from dishka import AsyncContainer

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_container_resolves_services(app_container: AsyncContainer, scope: AsyncContainer) -> None:
    # Container is the real Dishka container
    assert isinstance(app_container, AsyncContainer)

    # Can resolve core dependencies from DI
    db: Database = await scope.get(Database)
    assert db.name and isinstance(db.name, str)

    svc: EventService = await scope.get(EventService)
    assert isinstance(svc, EventService)
