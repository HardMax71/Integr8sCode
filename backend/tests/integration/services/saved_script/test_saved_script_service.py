import pytest
from dishka import AsyncContainer

from app.domain.saved_script import DomainSavedScriptCreate, DomainSavedScriptUpdate, SavedScriptNotFoundError
from app.services.saved_script_service import SavedScriptService

pytestmark = [pytest.mark.integration, pytest.mark.mongodb]


def _create_payload() -> DomainSavedScriptCreate:
    return DomainSavedScriptCreate(name="n", description=None, script="print(1)")


@pytest.mark.asyncio
async def test_crud_saved_script(scope: AsyncContainer) -> None:
    service: SavedScriptService = await scope.get(SavedScriptService)
    created = await service.create_saved_script(_create_payload(), user_id="u1")
    assert created.user_id == "u1"

    got = await service.get_saved_script(str(created.script_id), "u1")
    assert got and got.script_id == created.script_id

    out = await service.update_saved_script(str(created.script_id), "u1", DomainSavedScriptUpdate(name="new", script="p"))
    assert out and out.name == "new"

    lst = await service.list_saved_scripts("u1")
    assert any(s.script_id == created.script_id for s in lst)

    await service.delete_saved_script(str(created.script_id), "u1")
    with pytest.raises(SavedScriptNotFoundError):
        await service.get_saved_script(str(created.script_id), "u1")
