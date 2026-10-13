import pytest

from app.runtime_registry import DEFAULT_LANG, DEFAULT_LANG_VERSION, LANGUAGE_SPECS
from app.schemas_pydantic.execution import ExecutionRequest


def test_execution_request_valid_supported_runtime() -> None:
    req = ExecutionRequest(script="print('ok')", lang=DEFAULT_LANG, lang_version=DEFAULT_LANG_VERSION)
    assert (req.lang, req.lang_version) == (DEFAULT_LANG, DEFAULT_LANG_VERSION)


def test_execution_request_unsupported_language_raises() -> None:
    with pytest.raises(ValueError) as e:
        ExecutionRequest(script="print(1)", lang="rust", lang_version="1.0")
    assert "Language 'rust' not supported" in str(e.value)


def test_execution_request_unsupported_version_raises() -> None:
    with pytest.raises(ValueError) as e:
        ExecutionRequest(script="print(1)", lang="python", lang_version="9.9")
    assert "Version '9.9' not supported for python" in str(e.value)


@pytest.mark.parametrize(
    ("lang", "version"),
    [(lang, version) for lang, spec in LANGUAGE_SPECS.items() for version in spec["versions"]],
)
def test_execution_request_accepts_every_offered_version(lang: str, version: str) -> None:
    req = ExecutionRequest(script="x", lang=lang, lang_version=version)
    assert (req.lang, req.lang_version) == (lang, version)


@pytest.mark.parametrize(
    ("lang", "version"),
    [
        ("python", "3.7"),
        ("python", "3.10"),
        ("node", "18"),
        ("node", "20"),
        ("ruby", "3.1"),
        ("ruby", "3.2"),
        ("bash", "5.1"),
        ("bash", "5.2"),
        ("go", "1.20"),
        ("go", "1.22"),
    ],
)
def test_execution_request_rejects_dropped_version(lang: str, version: str) -> None:
    with pytest.raises(ValueError, match=f"Version '{version}' not supported for {lang}"):
        ExecutionRequest(script="x", lang=lang, lang_version=version)
