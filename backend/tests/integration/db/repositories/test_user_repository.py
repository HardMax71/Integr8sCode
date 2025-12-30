from datetime import datetime, timezone

import pytest
from app.db.repositories.user_repository import UserRepository
from app.domain.enums.user import UserRole
from app.domain.user.user_models import User as DomainUser
from app.domain.user.user_models import UserUpdate

pytestmark = pytest.mark.integration


@pytest.fixture()
async def repo(scope) -> UserRepository:  # type: ignore[valid-type]
    return await scope.get(UserRepository)


@pytest.mark.asyncio
async def test_create_get_update_delete_user(repo: UserRepository) -> None:
    # Create user
    user = DomainUser(
        user_id="",  # let repo assign
        username="alice",
        email="alice@example.com",
        role=UserRole.USER,
        is_active=True,
        is_superuser=False,
        hashed_password="h",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    created = await repo.create_user(user)
    assert created.user_id

    # Get by username
    fetched = await repo.get_user("alice")
    assert fetched and fetched.username == "alice"

    # Get by id
    by_id = await repo.get_user_by_id(created.user_id)
    assert by_id and by_id.user_id == created.user_id

    # List with search + role
    users = await repo.list_users(limit=10, offset=0, search="ali", role=UserRole.USER)
    assert any(u.username == "alice" for u in users)

    # Update
    upd = UserUpdate(email="alice2@example.com")
    updated = await repo.update_user(created.user_id, upd)
    assert updated and updated.email == "alice2@example.com"

    # Delete
    assert await repo.delete_user(created.user_id) is True
    assert await repo.get_user("alice") is None
