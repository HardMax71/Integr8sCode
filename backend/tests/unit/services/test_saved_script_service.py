from unittest.mock import AsyncMock

import pytest
import structlog

from app.db import SavedScriptRepository
from app.domain.execution import RuntimeNotSupportedError
from app.domain.saved_script import (
    DomainSavedScript,
    DomainSavedScriptCreate,
    DomainSavedScriptUpdate,
    SavedScriptNotFoundError,
)
from app.services.saved_script_service import SavedScriptService

pytestmark = pytest.mark.unit


def _stored(lang: str = "python", lang_version: str = "3.12") -> DomainSavedScript:
    return DomainSavedScript(name="s", script="x", script_id="sid", user_id="u1", lang=lang, lang_version=lang_version)


@pytest.fixture
def repo() -> AsyncMock:
    repo = AsyncMock(spec=SavedScriptRepository)
    repo.create_saved_script.return_value = _stored()
    repo.get_saved_script.return_value = _stored()
    return repo


@pytest.fixture
def service(repo: AsyncMock) -> SavedScriptService:
    return SavedScriptService(repo, structlog.get_logger("test"))


async def test_create_accepts_an_offered_runtime(service: SavedScriptService, repo: AsyncMock) -> None:
    create = DomainSavedScriptCreate(name="s", script="x", lang="go", lang_version="1.26")

    await service.create_saved_script(create, "u1")

    repo.create_saved_script.assert_awaited_once_with(create, "u1")


@pytest.mark.parametrize(("lang", "lang_version"), [("python", "3.7"), ("python", "9.9"), ("rust", "1.0")])
async def test_create_rejects_a_runtime_that_is_not_offered(
    service: SavedScriptService, repo: AsyncMock, lang: str, lang_version: str
) -> None:
    create = DomainSavedScriptCreate(name="s", script="x", lang=lang, lang_version=lang_version)

    with pytest.raises(RuntimeNotSupportedError, match=f"Runtime not supported: {lang} {lang_version}"):
        await service.create_saved_script(create, "u1")

    repo.create_saved_script.assert_not_awaited()


@pytest.mark.parametrize(
    ("stored", "update", "accepted"),
    [
        (_stored("python", "3.12"), DomainSavedScriptUpdate(lang_version="3.14"), True),
        (_stored("python", "3.12"), DomainSavedScriptUpdate(lang_version="3.7"), False),
        (_stored("go", "1.26"), DomainSavedScriptUpdate(lang_version="3.14"), False),
        (_stored("python", "3.12"), DomainSavedScriptUpdate(lang="node"), False),
        (_stored("python", "3.12"), DomainSavedScriptUpdate(lang="node", lang_version="26"), True),
        (_stored("python", "3.12"), DomainSavedScriptUpdate(lang="node", lang_version="18"), False),
        (_stored("python", "3.7"), DomainSavedScriptUpdate(name="renamed"), True),
    ],
    ids=[
        "version-only-offered",
        "version-only-dropped",
        "version-checked-against-stored-language",
        "language-only-checked-against-stored-version",
        "both-offered",
        "both-dropped",
        "no-runtime-change-skips-the-check",
    ],
)
async def test_update_checks_the_resulting_runtime(
    service: SavedScriptService,
    repo: AsyncMock,
    stored: DomainSavedScript,
    update: DomainSavedScriptUpdate,
    accepted: bool,
) -> None:
    repo.get_saved_script.return_value = stored

    if accepted:
        await service.update_saved_script("sid", "u1", update)
        repo.update_saved_script.assert_awaited_once_with("sid", "u1", update)
    else:
        with pytest.raises(RuntimeNotSupportedError):
            await service.update_saved_script("sid", "u1", update)
        repo.update_saved_script.assert_not_awaited()


async def test_update_of_a_missing_script_is_not_found(service: SavedScriptService, repo: AsyncMock) -> None:
    repo.get_saved_script.return_value = None

    with pytest.raises(SavedScriptNotFoundError):
        await service.update_saved_script("sid", "u1", DomainSavedScriptUpdate(lang_version="3.14"))

    repo.update_saved_script.assert_not_awaited()


async def test_reads_still_load_scripts_on_dropped_runtimes(service: SavedScriptService, repo: AsyncMock) -> None:
    old = _stored("python", "3.7")
    repo.get_saved_script.return_value = old
    repo.list_saved_scripts.return_value = [old]

    assert await service.get_saved_script("sid", "u1") == old
    assert (await service.list_saved_scripts("u1")).scripts == [old]
