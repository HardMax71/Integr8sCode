from datetime import datetime, timezone

import pytest
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import User
from app.services.saga.saga_service import SagaService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_saga_service_basic(scope: AsyncContainer) -> None:
    svc: SagaService = await scope.get(SagaService)
    user = User(
        user_id="u1",
        username="u1",
        email="u1@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    res = await svc.list_user_sagas(user)
    assert hasattr(res, "sagas") and isinstance(res.sagas, list)
