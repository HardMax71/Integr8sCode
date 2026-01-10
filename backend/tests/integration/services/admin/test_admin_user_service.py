from datetime import datetime, timezone

import pytest
from dishka import AsyncContainer

from app.core.database_context import Database
from app.domain.enums.user import UserRole
from app.services.admin import AdminUserService

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_get_user_overview_basic(scope: AsyncContainer) -> None:
    svc: AdminUserService = await scope.get(AdminUserService)
    db: Database = await scope.get(Database)
    await db.get_collection("users").insert_one({
        "user_id": "u1",
        "username": "bob",
        "email": "b@b.com",
        "role": UserRole.USER.value,
        "is_active": True,
        "is_superuser": False,
        "hashed_password": "h",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    overview = await svc.get_user_overview("u1", hours=1)
    assert overview.user.username == "bob"


@pytest.mark.asyncio
async def test_get_user_overview_user_not_found(scope: AsyncContainer) -> None:
    svc: AdminUserService = await scope.get(AdminUserService)
    with pytest.raises(ValueError):
        await svc.get_user_overview("missing")
