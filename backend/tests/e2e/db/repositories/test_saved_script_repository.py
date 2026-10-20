import pytest

from app.db.docs import SavedScriptDocument
from app.db.repositories import SavedScriptRepository
from app.domain.saved_script import SavedScriptChanges

pytestmark = pytest.mark.e2e


async def test_create_get_update_delete_saved_script(saved_script_repository: SavedScriptRepository) -> None:
    created = SavedScriptDocument(name="n", description=None, script="print(1)", user_id="u1")
    await saved_script_repository.create_saved_script(created)
    assert created.user_id == "u1" and created.script == "print(1)"

    # get by id/user
    got = await saved_script_repository.get_saved_script(created.script_id, "u1")
    assert got and got.script_id == created.script_id

    # update
    await saved_script_repository.update_saved_script(got, SavedScriptChanges(name="updated"))
    updated = await saved_script_repository.get_saved_script(created.script_id, "u1")
    assert updated and updated.name == "updated"

    # list
    scripts = await saved_script_repository.list_saved_scripts("u1")
    assert any(s.script_id == created.script_id for s in scripts)

    # delete
    await saved_script_repository.delete_saved_script(created.script_id, "u1")
    assert await saved_script_repository.get_saved_script(created.script_id, "u1") is None
