import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ServiceError

from app.services.saved_script_service import SavedScriptService
from app.domain.saved_script.models import DomainSavedScriptCreate, DomainSavedScriptUpdate
from app.domain.saved_script.models import DomainSavedScript
from datetime import datetime, timezone


pytestmark = pytest.mark.unit


@pytest.fixture()
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    return repo


def _create_payload() -> DomainSavedScriptCreate:
    return DomainSavedScriptCreate(name="n", description=None, script="print(1)")


@pytest.mark.asyncio
async def test_create_and_get_and_list_saved_script(mock_repo: AsyncMock) -> None:
    service = SavedScriptService(mock_repo)

    created = DomainSavedScript(script_id="sid", user_id="u1", name="n", description=None, script="s", lang="python", lang_version="3.11", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    mock_repo.create_saved_script = AsyncMock(return_value=created)
    out = await service.create_saved_script(_create_payload(), user_id="u1")
    assert out.user_id == "u1"

    # get success
    mock_repo.get_saved_script = AsyncMock(return_value=created)
    got = await service.get_saved_script(str(created.script_id), "u1")
    assert got.script_id == created.script_id

    # list
    mock_repo.list_saved_scripts = AsyncMock(return_value=[created])
    lst = await service.list_saved_scripts("u1")
    assert len(lst) == 1


@pytest.mark.asyncio
async def test_get_not_found_raises_404(mock_repo: AsyncMock) -> None:
    service = SavedScriptService(mock_repo)
    mock_repo.get_saved_script = AsyncMock(return_value=None)
    with pytest.raises(ServiceError) as ei:
        await service.get_saved_script("sid", "u1")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_update_and_delete_saved_script(mock_repo: AsyncMock) -> None:
    service = SavedScriptService(mock_repo)
    payload = DomainSavedScriptUpdate(name="new", script="p")
    # update path: update then get returns doc
    updated = DomainSavedScript(script_id="sid", user_id="u1", name="new", description=None, script="p", lang="python", lang_version="3.11", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    mock_repo.update_saved_script = AsyncMock()
    mock_repo.get_saved_script = AsyncMock(return_value=updated)
    out = await service.update_saved_script("sid", "u1", payload)
    assert out.name == "new"

    # update path: get returns None -> ServiceError
    mock_repo.get_saved_script = AsyncMock(return_value=None)
    with pytest.raises(ServiceError):
        await service.update_saved_script("sid", "u1", payload)

    # delete path
    mock_repo.delete_saved_script = AsyncMock()
    await service.delete_saved_script("sid", "u1")
