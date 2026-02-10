import logging
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from app.domain.admin import SystemSettings
from app.services.runtime_settings import RuntimeSettingsLoader
from app.settings import Settings

pytestmark = pytest.mark.unit

_logger = logging.getLogger("test.services.runtime_settings")


def _make_settings() -> Settings:
    """Create settings with values that pass SystemSettings validation."""
    base = Settings(config_path="config.test.toml")
    return base.model_copy(update={
        "K8S_POD_EXECUTION_TIMEOUT": 30,
        "K8S_POD_MEMORY_LIMIT": "128Mi",
        "K8S_POD_CPU_LIMIT": "1000m",
        "K8S_MAX_CONCURRENT_PODS": 5,
        "ACCESS_TOKEN_EXPIRE_MINUTES": 60,
    })


def _make_loader(
    *,
    repo_return: SystemSettings | None = None,
    repo_side_effect: Exception | None = None,
) -> tuple[RuntimeSettingsLoader, AsyncMock]:
    repo = AsyncMock()
    if repo_side_effect:
        repo.get_system_settings.side_effect = repo_side_effect
    else:
        repo.get_system_settings.return_value = repo_return or SystemSettings()
    loader = RuntimeSettingsLoader(repo=repo, settings=_make_settings(), logger=_logger)
    return loader, repo


@pytest.mark.asyncio
async def test_returns_settings_from_repo() -> None:
    db_settings = SystemSettings(max_timeout_seconds=999)
    loader, repo = _make_loader(repo_return=db_settings)

    result = await loader.get_effective_settings()

    assert result.max_timeout_seconds == 999


@pytest.mark.asyncio
async def test_passes_toml_defaults_to_repo() -> None:
    loader, repo = _make_loader()

    await loader.get_effective_settings()

    defaults = repo.get_system_settings.call_args.kwargs["defaults"]
    assert defaults.max_timeout_seconds == 30
    assert defaults.memory_limit == "128Mi"
    assert defaults.cpu_limit == "1000m"
    assert defaults.max_concurrent_executions == 5
    assert defaults.session_timeout_minutes == 60


@pytest.mark.asyncio
async def test_falls_back_to_toml_on_db_error() -> None:
    loader, repo = _make_loader(repo_side_effect=ConnectionError("DB down"))

    result = await loader.get_effective_settings()

    assert result.max_timeout_seconds == 30
    assert result.memory_limit == "128Mi"


@pytest.mark.asyncio
async def test_caches_result() -> None:
    loader, repo = _make_loader()

    first = await loader.get_effective_settings()
    second = await loader.get_effective_settings()

    assert first is second
    repo.get_system_settings.assert_called_once()


@pytest.mark.asyncio
async def test_cache_expires_after_ttl() -> None:
    loader, repo = _make_loader()
    loader._cache_ttl = 0.0  # noqa: SLF001

    await loader.get_effective_settings()
    await loader.get_effective_settings()

    assert repo.get_system_settings.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_cache_forces_reload() -> None:
    loader, repo = _make_loader()

    await loader.get_effective_settings()
    loader.invalidate_cache()
    await loader.get_effective_settings()

    assert repo.get_system_settings.call_count == 2


@pytest.mark.asyncio
async def test_cache_respects_ttl_boundary() -> None:
    loader, repo = _make_loader()

    await loader.get_effective_settings()
    loader._cache_time = monotonic() - 61.0  # noqa: SLF001
    await loader.get_effective_settings()

    assert repo.get_system_settings.call_count == 2


@pytest.mark.asyncio
async def test_db_error_result_is_still_cached() -> None:
    loader, repo = _make_loader(repo_side_effect=ConnectionError("DB down"))

    await loader.get_effective_settings()
    await loader.get_effective_settings()

    repo.get_system_settings.assert_called_once()
