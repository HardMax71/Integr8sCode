import uuid

import pytest

from app.db.docs import UserDocument
from app.domain.enums import UserRole
from app.domain.exceptions import NotFoundError
from app.services.admin import AdminUserService

pytestmark = [pytest.mark.e2e]


async def test_get_user_overview_basic(admin_user_service: AdminUserService) -> None:
    uid = uuid.uuid4().hex[:8]
    await UserDocument(
        user_id=f"u_{uid}",
        username=f"bob_{uid}",
        email=f"bob_{uid}@example.com",
        role=UserRole.USER,
        hashed_password="h",
    ).insert()

    overview = await admin_user_service.get_user_overview(f"u_{uid}", hours=1)
    assert overview.user.username == f"bob_{uid}"


async def test_get_user_overview_user_not_found(admin_user_service: AdminUserService) -> None:
    with pytest.raises(NotFoundError):
        await admin_user_service.get_user_overview("missing")
