import ast
import inspect
from datetime import datetime, timezone
from typing import Any

import pytest

from app.db.docs import ExecutionDocument, SavedScriptDocument
from app.domain.enums import ExecutionStatus
from app.domain.execution import DomainExecution, DomainExecutionCreate, ExecutionResultDomain
from app.domain.saved_script import DomainSavedScript, DomainSavedScriptCreate
from app.runtime_registry import (
    DEFAULT_LANG,
    DEFAULT_LANG_VERSION,
    EXAMPLE_SCRIPTS,
    LANGUAGE_SPECS,
    POD_RUNTIME_CONFIGS,
    RUNTIME_REGISTRY,
    LanguageSpec,
    PodRuntimeConfig,
    RuntimeConfig,
    _make_runtime_configs,
)
from app.schemas_pydantic.execution import ExecutionBase, ExecutionRequest
from app.schemas_pydantic.saved_script import SavedScriptCreateRequest
from app.services.execution_service import ExecutionService
from app.settings import Settings

pytestmark = pytest.mark.unit


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@pytest.mark.parametrize("lang", list(LANGUAGE_SPECS))
def test_versions_are_unique_and_listed_newest_first(lang: str) -> None:
    versions = LANGUAGE_SPECS[lang]["versions"]
    assert versions
    assert versions == sorted(set(versions), key=_version_key, reverse=True)


@pytest.mark.parametrize("lang", list(LANGUAGE_SPECS))
def test_registry_builds_image_and_command_for_every_version(lang: str) -> None:
    spec = LANGUAGE_SPECS[lang]
    file_name = f"main.{spec['file_ext']}"

    assert list(RUNTIME_REGISTRY[lang]) == spec["versions"]
    for version, cfg in RUNTIME_REGISTRY[lang].items():
        assert cfg.image == spec["image_tpl"].format(version=version)
        assert cfg.file_name == file_name
        assert cfg.command == [*spec["interpreter"], f"/scripts/{file_name}"]


def test_script_path_is_always_the_last_argument() -> None:
    spec: LanguageSpec = {
        "versions": ["1.99"],
        "image_tpl": "rust:{version}-slim",
        "file_ext": "rs",
        "interpreter": ["sh", "-c", 'rustc -o /tmp/main "$0" && exec /tmp/main {file}'],
    }

    assert _make_runtime_configs({"rust": spec}) == {
        "rust": {
            "1.99": RuntimeConfig(
                image="rust:1.99-slim",
                file_name="main.rs",
                command=["sh", "-c", 'rustc -o /tmp/main "$0" && exec /tmp/main {file}', "/scripts/main.rs"],
            )
        }
    }


def test_settings_supported_runtimes_mirror_specs(test_settings: Settings) -> None:
    assert {lang: (info.versions, info.file_ext) for lang, info in test_settings.SUPPORTED_RUNTIMES.items()} == {
        lang: (spec["versions"], spec["file_ext"]) for lang, spec in LANGUAGE_SPECS.items()
    }


def test_default_runtime_is_the_newest_python() -> None:
    assert DEFAULT_LANG == "python"
    assert DEFAULT_LANG_VERSION == max(LANGUAGE_SPECS["python"]["versions"], key=_version_key)
    assert DEFAULT_LANG_VERSION in RUNTIME_REGISTRY[DEFAULT_LANG]


def test_every_lang_version_default_uses_the_registry_default() -> None:
    now = datetime.now(timezone.utc)
    defaults: dict[str, Any] = {
        "ExecutionRequest": ExecutionRequest(script="x"),
        "ExecutionBase": ExecutionBase(script="x"),
        "SavedScriptCreateRequest": SavedScriptCreateRequest(name="n", script="x"),
        "DomainExecution": DomainExecution(),
        "DomainExecutionCreate": DomainExecutionCreate(script="x", user_id="u"),
        "ExecutionResultDomain": ExecutionResultDomain(
            execution_id="e", status=ExecutionStatus.COMPLETED, exit_code=0, stdout="", stderr="", created_at=now
        ),
        "DomainSavedScriptCreate": DomainSavedScriptCreate(name="n", script="x"),
        "DomainSavedScript": DomainSavedScript(name="n", script="x"),
    }
    for name, obj in defaults.items():
        assert (obj.lang, obj.lang_version) == (DEFAULT_LANG, DEFAULT_LANG_VERSION), name

    for document in (ExecutionDocument, SavedScriptDocument):
        fields = document.model_fields
        assert (fields["lang"].default, fields["lang_version"].default) == (DEFAULT_LANG, DEFAULT_LANG_VERSION)

    for method in (ExecutionService.execute_script, ExecutionService.execute_script_idempotent):
        params = inspect.signature(method).parameters
        assert (params["lang"].default, params["lang_version"].default) == (DEFAULT_LANG, DEFAULT_LANG_VERSION)


def test_pod_runtime_configs_default_unless_a_language_needs_more() -> None:
    assert set(POD_RUNTIME_CONFIGS) == set(LANGUAGE_SPECS)
    assert {lang for lang, cfg in POD_RUNTIME_CONFIGS.items() if cfg != PodRuntimeConfig()} == {"go"}
    assert POD_RUNTIME_CONFIGS["go"] == PodRuntimeConfig(
        env={"HOME": "/tmp", "GOCACHE": "/tmp/go-cache"},
        tmp_size="64Mi",
        min_cpu="1000m",
        min_memory="320Mi",
        min_timeout_seconds=30,
    )


def test_every_language_has_an_example_script() -> None:
    assert set(EXAMPLE_SCRIPTS) == set(LANGUAGE_SPECS)
    assert all(script.strip() for script in EXAMPLE_SCRIPTS.values())


@pytest.mark.parametrize("version", LANGUAGE_SPECS["python"]["versions"])
def test_python_example_parses_on_every_offered_version(version: str) -> None:
    major, minor = _version_key(version)
    ast.parse(EXAMPLE_SCRIPTS["python"], feature_version=(major, minor))


@pytest.mark.parametrize(("minimum", "configured", "expected"), [(None, 5, 5), (30, 5, 30), (30, 60, 60)])
def test_pod_timeout_is_raised_to_the_language_minimum(minimum: int | None, configured: int, expected: int) -> None:
    assert PodRuntimeConfig(min_timeout_seconds=minimum).timeout_for(configured) == expected
