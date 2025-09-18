import pytest
from datetime import datetime, timezone

from app.services.saga.saga_service import SagaService

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_saga_service_basic(scope) -> None:  # type: ignore[valid-type]
    svc: SagaService = await scope.get(SagaService)
    from app.domain.user import User as DomainUser
    from app.domain.enums.user import UserRole
    user = DomainUser(
        user_id="u1",
        username="u1",
        email="u1@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="x",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    res = await svc.list_user_sagas(user)
    assert hasattr(res, "sagas") and isinstance(res.sagas, list)
