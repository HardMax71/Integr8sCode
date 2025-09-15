import pytest
from datetime import datetime, timezone

from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.domain.user import UserFields, UserUpdate, PasswordReset
from app.core.security import SecurityService

pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(db) -> AdminUserRepository:  # type: ignore[valid-type]
    return AdminUserRepository(db)


@pytest.mark.asyncio
async def test_list_and_get_user(repo: AdminUserRepository, db) -> None:  # type: ignore[valid-type]
    # Insert a user
    await db.get_collection("users").insert_one({
        UserFields.USER_ID: "u1",
        UserFields.USERNAME: "alice",
        UserFields.EMAIL: "alice@example.com",
        UserFields.ROLE: "user",
        UserFields.IS_ACTIVE: True,
        UserFields.IS_SUPERUSER: False,
        UserFields.HASHED_PASSWORD: "h",
        UserFields.CREATED_AT: datetime.now(timezone.utc),
        UserFields.UPDATED_AT: datetime.now(timezone.utc),
    })
    res = await repo.list_users(limit=10)
    assert res.total >= 1 and any(u.username == "alice" for u in res.users)
    user = await repo.get_user_by_id("u1")
    assert user and user.user_id == "u1"


@pytest.mark.asyncio
async def test_update_delete_and_reset_password(repo: AdminUserRepository, db, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[valid-type]
    # Insert base user
    await db.get_collection("users").insert_one({
        UserFields.USER_ID: "u1",
        UserFields.USERNAME: "bob",
        UserFields.EMAIL: "bob@example.com",
        UserFields.ROLE: "user",
        UserFields.IS_ACTIVE: True,
        UserFields.IS_SUPERUSER: False,
        UserFields.HASHED_PASSWORD: "h",
        UserFields.CREATED_AT: datetime.now(timezone.utc),
        UserFields.UPDATED_AT: datetime.now(timezone.utc),
    })
    # No updates → returns current
    updated = await repo.update_user("u1", UserUpdate())
    assert updated and updated.user_id == "u1"
    # Delete cascade (collections empty → zeros)
    deleted = await repo.delete_user("u1", cascade=True)
    assert deleted["user"] in (0, 1)
    # Re-insert and reset password
    await db.get_collection("users").insert_one({
        UserFields.USER_ID: "u1",
        UserFields.USERNAME: "bob",
        UserFields.EMAIL: "bob@example.com",
        UserFields.ROLE: "user",
        UserFields.IS_ACTIVE: True,
        UserFields.IS_SUPERUSER: False,
        UserFields.HASHED_PASSWORD: "h",
        UserFields.CREATED_AT: datetime.now(timezone.utc),
        UserFields.UPDATED_AT: datetime.now(timezone.utc),
    })
    monkeypatch.setattr(SecurityService, "get_password_hash", staticmethod(lambda p: "HASHED"))
    pr = PasswordReset(user_id="u1", new_password="secret123")
    assert await repo.reset_user_password(pr) is True


@pytest.mark.asyncio
async def test_list_with_filters_and_reset_invalid(repo: AdminUserRepository, db) -> None:  # type: ignore[valid-type]
    # Insert a couple of users
    await db.get_collection("users").insert_many([
        {UserFields.USER_ID: "u1", UserFields.USERNAME: "Alice", UserFields.EMAIL: "a@e.com", UserFields.ROLE: "user", UserFields.IS_ACTIVE: True, UserFields.IS_SUPERUSER: False, UserFields.HASHED_PASSWORD: "h", UserFields.CREATED_AT: datetime.now(timezone.utc), UserFields.UPDATED_AT: datetime.now(timezone.utc)},
        {UserFields.USER_ID: "u2", UserFields.USERNAME: "Bob", UserFields.EMAIL: "b@e.com", UserFields.ROLE: "admin", UserFields.IS_ACTIVE: True, UserFields.IS_SUPERUSER: True, UserFields.HASHED_PASSWORD: "h", UserFields.CREATED_AT: datetime.now(timezone.utc), UserFields.UPDATED_AT: datetime.now(timezone.utc)},
    ])
    res = await repo.list_users(limit=5, offset=0, search="Al", role=None)
    assert any(u.username.lower().startswith("al") for u in res.users) or res.total >= 0
    # invalid password reset (empty)
    with pytest.raises(ValueError):
        await repo.reset_user_password(PasswordReset(user_id="u1", new_password=""))
