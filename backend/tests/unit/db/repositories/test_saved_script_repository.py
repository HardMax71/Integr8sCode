import pytest
from unittest.mock import AsyncMock, MagicMock

from motor.motor_asyncio import AsyncIOMotorCollection

from app.db.repositories.saved_script_repository import SavedScriptRepository
from app.domain.saved_script.models import DomainSavedScriptCreate, DomainSavedScriptUpdate


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> SavedScriptRepository:
    # default behaviors used across tests
    mock_db.saved_scripts.insert_one = AsyncMock(return_value=MagicMock(inserted_id="oid1"))
    mock_db.saved_scripts.find_one = AsyncMock()
    mock_db.saved_scripts.update_one = AsyncMock()
    mock_db.saved_scripts.delete_one = AsyncMock()
    mock_db.saved_scripts.find = AsyncMock()
    return SavedScriptRepository(mock_db)


@pytest.mark.asyncio
async def test_create_and_get_saved_script(repo: SavedScriptRepository, mock_db) -> None:
    create = DomainSavedScriptCreate(name="n", lang="python", lang_version="3.11", description=None, script="print(1)")
    # Simulate read after insert returning DB doc
    mock_db.saved_scripts.find_one.return_value = {
        "script_id": "sid1",
        "user_id": "u1",
        "name": create.name,
        "script": create.script,
        "lang": create.lang,
        "lang_version": create.lang_version,
        "description": create.description,
    }

    created = await repo.create_saved_script(create, user_id="u1")
    assert created.user_id == "u1" and created.script == "print(1)"
    mock_db.saved_scripts.insert_one.assert_called_once()

    # get by id/user
    mock_db.saved_scripts.find_one.return_value = {
        "script_id": created.script_id,
        "user_id": created.user_id,
        "name": created.name,
        "script": created.script,
        "lang": created.lang,
        "lang_version": created.lang_version,
        "description": created.description,
    }
    got = await repo.get_saved_script(created.script_id, "u1")
    assert got and got.script_id == created.script_id


@pytest.mark.asyncio
async def test_create_saved_script_missing_after_insert_raises(repo: SavedScriptRepository, mock_db) -> None:
    create = DomainSavedScriptCreate(name="n2", lang="python", lang_version="3.11", description=None, script="print(2)")
    mock_db.saved_scripts.find_one = AsyncMock(return_value=None)
    with pytest.raises(ValueError):
        await repo.create_saved_script(create, user_id="u2")


@pytest.mark.asyncio
async def test_update_and_delete_saved_script(repo: SavedScriptRepository, mock_db) -> None:
    await repo.update_saved_script("sid", "u1", DomainSavedScriptUpdate(name="updated"))
    mock_db.saved_scripts.update_one.assert_called_once()

    await repo.delete_saved_script("sid", "u1")
    mock_db.saved_scripts.delete_one.assert_called_once()


@pytest.mark.asyncio
async def test_list_saved_scripts(repo: SavedScriptRepository, mock_db) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def __aiter__(self):
            async def gen():
                for d in self._docs:
                    yield d
            return gen()

    doc = {
        "script_id": "sid1",
        "user_id": "u1",
        "name": "n",
        "script": "c",
        "lang": "python",
        "lang_version": "3.11",
        "description": None,
    }
    mock_db.saved_scripts.find = MagicMock(return_value=Cursor([doc]))
    scripts = await repo.list_saved_scripts("u1")
    assert len(scripts) == 1 and scripts[0].user_id == "u1"
