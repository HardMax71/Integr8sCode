import pytest

from app.db.repositories.saved_script_repository import SavedScriptRepository
from app.domain.saved_script import DomainSavedScriptCreate, DomainSavedScriptUpdate

pytestmark = pytest.mark.unit

@pytest.mark.asyncio
async def test_create_get_update_delete_saved_script(db) -> None:  # type: ignore[valid-type]
    repo = SavedScriptRepository(db)
    create = DomainSavedScriptCreate(name="n", lang="python", lang_version="3.11", description=None, script="print(1)")
    created = await repo.create_saved_script(create, user_id="u1")
    assert created.user_id == "u1" and created.script == "print(1)"

    # get by id/user
    got = await repo.get_saved_script(created.script_id, "u1")
    assert got and got.script_id == created.script_id

    # update
    await repo.update_saved_script(created.script_id, "u1", DomainSavedScriptUpdate(name="updated"))
    updated = await repo.get_saved_script(created.script_id, "u1")
    assert updated and updated.name == "updated"

    # list
    scripts = await repo.list_saved_scripts("u1")
    assert any(s.script_id == created.script_id for s in scripts)

    # delete
    await repo.delete_saved_script(created.script_id, "u1")
    assert await repo.get_saved_script(created.script_id, "u1") is None
