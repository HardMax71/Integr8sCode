import pytest
from unittest.mock import AsyncMock, MagicMock

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

from app.db.repositories.admin.admin_user_repository import AdminUserRepository
from app.domain.admin.user_models import UserFields, UserUpdate, PasswordReset


pytestmark = pytest.mark.unit


# mock_db fixture now provided by main conftest.py


@pytest.fixture()
def repo(mock_db) -> AdminUserRepository:
    return AdminUserRepository(mock_db)


@pytest.mark.asyncio
async def test_list_and_get_user(repo: AdminUserRepository, mock_db: AsyncIOMotorDatabase) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    mock_db.users.count_documents = AsyncMock(return_value=1)
    mock_db.users.find.return_value = Cursor([{UserFields.USER_ID: "u1", UserFields.USERNAME: "a", UserFields.EMAIL: "a@e.com", UserFields.ROLE: "user"}])
    res = await repo.list_users(limit=10)
    assert res.total == 1 and len(res.users) == 1

    mock_db.users.find_one = AsyncMock(return_value={UserFields.USER_ID: "u1", UserFields.USERNAME: "a", UserFields.EMAIL: "a@e.com", UserFields.ROLE: "user"})
    user = await repo.get_user_by_id("u1")
    assert user and user.user_id == "u1"


@pytest.mark.asyncio
async def test_update_delete_and_reset_password(repo: AdminUserRepository, mock_db: AsyncIOMotorDatabase) -> None:
    mock_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_db.users.find_one = AsyncMock(return_value={UserFields.USER_ID: "u1", UserFields.USERNAME: "a", UserFields.EMAIL: "a@e.com", UserFields.ROLE: "user"})
    updated = await repo.update_user("u1", UserUpdate())
    # No updates -> should just return current doc
    assert updated and updated.user_id == "u1"

    # cascade delete counts
    for c in (mock_db.executions, mock_db.saved_scripts, mock_db.notifications, mock_db.user_settings, mock_db.events, mock_db.sagas):
        c.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    mock_db.users.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    deleted = await repo.delete_user("u1", cascade=True)
    assert deleted["user"] == 1

    # reset password
    mock_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    pr = PasswordReset(user_id="u1", new_password="secret123")
    assert await repo.reset_user_password(pr) is True


@pytest.mark.asyncio
async def test_list_with_filters_and_reset_invalid(repo: AdminUserRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # search+role
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def skip(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    mock_db.users.count_documents = AsyncMock(return_value=0)
    mock_db.users.find.return_value = Cursor([])
    res = await repo.list_users(limit=5, offset=0, search="Al", role="user")
    assert res.total == 0 and res.users == []

    # invalid password reset (empty)
    with pytest.raises(ValueError):
        await repo.reset_user_password(PasswordReset(user_id="u1", new_password=""))


@pytest.mark.asyncio
async def test_update_user_with_password_hash(repo: AdminUserRepository, mock_db: AsyncIOMotorDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force an update with password set
    from app.core.security import SecurityService
    monkeypatch.setattr(SecurityService, "get_password_hash", staticmethod(lambda p: "HASHED"))
    upd = UserUpdate(password="newpassword123")
    mock_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_db.users.find_one = AsyncMock(return_value={UserFields.USER_ID: "u1", UserFields.USERNAME: "a", UserFields.EMAIL: "a@e.com", UserFields.ROLE: "user"})
    user = await repo.update_user("u1", upd)
    assert user and user.user_id == "u1"


@pytest.mark.asyncio
async def test_admin_user_exceptions(repo: AdminUserRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # list_users exception
    mock_db.users.count_documents = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.list_users(limit=1)

    # get_user_by_id exception
    mock_db.users.find_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.get_user_by_id("u1")

    # update_user exception
    from app.domain.admin.user_models import UserUpdate
    mock_db.users.update_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.update_user("u1", UserUpdate(password="x"))

    # delete_user exception
    mock_db.users.delete_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.delete_user("u1")

    # reset password exception
    mock_db.users.update_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.reset_user_password(PasswordReset(user_id="u1", new_password="p@ssw0rd"))
