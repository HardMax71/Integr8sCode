import pytest
from app.db.docs import UserDocument
from app.domain.enums import UserRole
from app.domain.exceptions import NotFoundError
from app.services.admin import AdminUserService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb]


@pytest.mark.asyncio
async def test_get_user_overview_basic(scope: AsyncContainer) -> None:
    svc: AdminUserService = await scope.get(AdminUserService)
    await UserDocument(
        user_id="u1",
        username="bob",
        email="b@b.com",
        role=UserRole.USER,
        hashed_password="h",
    ).insert()

    overview = await svc.get_user_overview("u1", hours=1)
    assert overview.user.username == "bob"


@pytest.mark.asyncio
async def test_get_user_overview_user_not_found(scope: AsyncContainer) -> None:
    svc: AdminUserService = await scope.get(AdminUserService)
    with pytest.raises(NotFoundError):
        await svc.get_user_overview("missing")
