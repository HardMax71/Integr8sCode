from unittest.mock import AsyncMock

import pytest
import structlog

from app.db import SavedScriptRepository
from app.db.docs import SavedScriptDocument
from app.domain.execution import RuntimeNotSupportedError
from app.domain.saved_script import SavedScriptChanges, SavedScriptNotFoundError
from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION, LANGUAGE_SPECS
from app.services.saved_script_service import SavedScriptService

pytestmark = pytest.mark.unit


def _stored(lang: str = DEFAULT_LANG, lang_version: str = DEFAULT_LANG_VERSION) -> SavedScriptDocument:
    return SavedScriptDocument(
        name="s", script="x", script_id="sid", user_id="u1", lang=lang, lang_version=lang_version
    )


@pytest.fixture
def repo() -> AsyncMock:
    repo = AsyncMock(spec=SavedScriptRepository)
    repo.get_saved_script.return_value = _stored()
    return repo


@pytest.fixture
def service(repo: AsyncMock) -> SavedScriptService:
    return SavedScriptService(repo, structlog.get_logger("test"))


async def test_create_accepts_an_offered_runtime(service: SavedScriptService, repo: AsyncMock) -> None:
    go_version = LANGUAGE_SPECS["go"]["versions"][0]

    await service.create_saved_script(
        user_id="u1", name="s", script="x", lang="go", lang_version=go_version, description=None
    )

    repo.create_saved_script.assert_awaited_once()
    (script,) = repo.create_saved_script.await_args.args
    assert (script.user_id, script.name, script.lang, script.lang_version) == ("u1", "s", "go", go_version)


@pytest.mark.parametrize(("lang", "lang_version"), [("python", "3.7"), ("python", "9.9"), ("rust", "1.0")])
async def test_create_rejects_a_runtime_that_is_not_offered(
    service: SavedScriptService, repo: AsyncMock, lang: str, lang_version: str
) -> None:
    with pytest.raises(RuntimeNotSupportedError, match=f"Runtime not supported: {lang} {lang_version}"):
        await service.create_saved_script(
            user_id="u1", name="s", script="x", lang=lang, lang_version=lang_version, description=None
        )

    repo.create_saved_script.assert_not_awaited()


@pytest.mark.parametrize(
    ("stored_runtime", "changes", "accepted"),
    [
        (
            (DEFAULT_LANG, DEFAULT_LANG_VERSION),
            SavedScriptChanges(lang_version=LANGUAGE_SPECS["python"]["versions"][-1]),
            True,
        ),
        ((DEFAULT_LANG, DEFAULT_LANG_VERSION), SavedScriptChanges(lang_version="3.7"), False),
        (("go", LANGUAGE_SPECS["go"]["versions"][0]), SavedScriptChanges(lang_version=DEFAULT_LANG_VERSION), False),
        ((DEFAULT_LANG, DEFAULT_LANG_VERSION), SavedScriptChanges(lang="node"), False),
        (
            (DEFAULT_LANG, DEFAULT_LANG_VERSION),
            SavedScriptChanges(lang="node", lang_version=LANGUAGE_SPECS["node"]["versions"][0]),
            True,
        ),
        ((DEFAULT_LANG, DEFAULT_LANG_VERSION), SavedScriptChanges(lang="node", lang_version="18"), False),
        (("python", "3.7"), SavedScriptChanges(name="renamed"), True),
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
    stored_runtime: tuple[str, str],
    changes: SavedScriptChanges,
    accepted: bool,
) -> None:
    stored = _stored(*stored_runtime)
    repo.get_saved_script.return_value = stored

    if accepted:
        await service.update_saved_script("sid", "u1", changes)
        repo.update_saved_script.assert_awaited_once_with(stored, changes)
    else:
        with pytest.raises(RuntimeNotSupportedError):
            await service.update_saved_script("sid", "u1", changes)
        repo.update_saved_script.assert_not_awaited()


async def test_update_of_a_missing_script_is_not_found(service: SavedScriptService, repo: AsyncMock) -> None:
    repo.get_saved_script.return_value = None

    with pytest.raises(SavedScriptNotFoundError):
        await service.update_saved_script("sid", "u1", SavedScriptChanges(lang_version=DEFAULT_LANG_VERSION))

    repo.update_saved_script.assert_not_awaited()


async def test_reads_still_load_scripts_on_dropped_runtimes(service: SavedScriptService, repo: AsyncMock) -> None:
    old = _stored("python", "3.7")
    repo.get_saved_script.return_value = old
    repo.list_saved_scripts.return_value = [old]

    assert await service.get_saved_script("sid", "u1") == old
    assert await service.list_saved_scripts("u1") == [old]
