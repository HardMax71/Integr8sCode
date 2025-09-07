import pytest
from unittest.mock import AsyncMock, MagicMock

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.repositories.user_repository import UserRepository
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user import UserInDB


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> UserRepository:
    # default behaviours
    mock_db.users.find_one = AsyncMock()
    mock_db.users.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid"))
    mock_db.users.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_db.users.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    mock_db.users.find = AsyncMock()
    return UserRepository(mock_db)


@pytest.mark.asyncio
async def test_get_user_found(repo: UserRepository, mock_db) -> None:
    user_doc = {
        "user_id": "u1",
        "username": "alice",
        "email": "alice@example.com",
        "hashed_password": "hash",
        "role": UserRole.USER,
    }
    mock_db.users.find_one.return_value = user_doc

    user = await repo.get_user("alice")

    assert user is not None
    assert user.username == "alice"
    mock_db.users.find_one.assert_called_once_with({"username": "alice"})


@pytest.mark.asyncio
async def test_get_user_not_found(repo: UserRepository, mock_db) -> None:
    mock_db.users.find_one.return_value = None
    assert await repo.get_user("missing") is None


@pytest.mark.asyncio
async def test_create_user_assigns_id_and_inserts(repo: UserRepository, mock_db) -> None:
    u = UserInDB(username="bob", email="bob@example.com", hashed_password="h")
    # remove id so repository must set it
    u.user_id = ""

    created = await repo.create_user(u)

    assert created.user_id  # should be set
    mock_db.users.insert_one.assert_called_once()


@pytest.mark.asyncio
async def test_get_user_by_id(repo: UserRepository, mock_db) -> None:
    mock_db.users.find_one.return_value = {
        "user_id": "u2",
        "username": "eve",
        "email": "eve@example.com",
        "hashed_password": "h",
        "role": UserRole.ADMIN,
    }
    user = await repo.get_user_by_id("u2")
    assert user and user.user_id == "u2" and user.role == UserRole.ADMIN
    mock_db.users.find_one.assert_called_once_with({"user_id": "u2"})


@pytest.mark.asyncio
async def test_list_users_with_search_and_role(repo: UserRepository, mock_db) -> None:
    # Build a minimal async cursor stub
    class Cursor:
        def __init__(self, docs: list[dict]):
            self._docs = docs
        def skip(self, *_args, **_kwargs):
            return self
        def limit(self, *_args, **_kwargs):
            return self
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    docs = [
        {
            "user_id": "u1",
            "username": "Alice",
            "email": "alice@example.com",
            "hashed_password": "h",
            "role": UserRole.USER,
        }
    ]
    mock_db.users.find = MagicMock(return_value=Cursor(docs))

    users = await repo.list_users(limit=10, offset=5, search="ali.*", role=UserRole.USER)

    # Verify query composition: the regex should be escaped, role value used
    q = mock_db.users.find.call_args[0][0]
    assert q["role"] == UserRole.USER.value
    assert "$or" in q and all("$regex" in c.get("username", {}) or "$regex" in c.get("email", {}) for c in q["$or"])  # noqa: SIM115
    assert len(users) == 1 and users[0].username.lower() == "alice"


@pytest.mark.asyncio
async def test_update_user_success(repo: UserRepository, mock_db) -> None:
    mock_db.users.update_one.return_value = MagicMock(modified_count=1)
    # when modified, repo fetches the user
    mock_db.users.find_one.return_value = {
        "user_id": "u3",
        "username": "joe",
        "email": "joe@example.com",
        "hashed_password": "h",
        "role": UserRole.USER,
    }
    updated = await repo.update_user("u3", UserInDB(username="joe", email="joe@example.com", hashed_password="h"))
    assert updated and updated.user_id == "u3"


@pytest.mark.asyncio
async def test_update_user_noop(repo: UserRepository, mock_db) -> None:
    mock_db.users.update_one.return_value = MagicMock(modified_count=0)
    res = await repo.update_user("u4", UserInDB(username="x", email="x@e.com", hashed_password="h"))
    assert res is None


@pytest.mark.asyncio
async def test_delete_user(repo: UserRepository, mock_db) -> None:
    mock_db.users.delete_one.return_value = MagicMock(deleted_count=1)
    assert await repo.delete_user("u5") is True
    mock_db.users.delete_one.return_value = MagicMock(deleted_count=0)
    assert await repo.delete_user("u6") is False
