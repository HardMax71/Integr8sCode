from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from app.domain.admin import SystemSettings
from app.services.admin import AdminSettingsService

pytestmark = pytest.mark.unit

_logger = structlog.get_logger("test.services.admin_settings")


def _make_service(
    *,
    repo_return: SystemSettings | None = None,
) -> tuple[AdminSettingsService, AsyncMock, MagicMock]:
    repo = AsyncMock()
    repo.update_system_settings.return_value = repo_return or SystemSettings()
    repo.reset_system_settings.return_value = SystemSettings()

    runtime = MagicMock()
    runtime.get_effective_settings = AsyncMock(return_value=repo_return or SystemSettings())
    runtime.invalidate_cache = MagicMock()

    service = AdminSettingsService(repository=repo, runtime_settings=runtime, logger=_logger)
    return service, repo, runtime


async def test_get_delegates_to_runtime_loader() -> None:
    expected = SystemSettings(max_timeout_seconds=42)
    service, repo, runtime = _make_service(repo_return=expected)

    result = await service.get_system_settings("u1")

    runtime.get_effective_settings.assert_called_once()
    repo.get_system_settings.assert_not_called()
    assert result.max_timeout_seconds == 42


async def test_update_calls_repo_and_invalidates_cache() -> None:
    new_settings = SystemSettings(max_timeout_seconds=600)
    service, repo, runtime = _make_service()
    repo.update_system_settings.return_value = new_settings

    result = await service.update_system_settings(new_settings, "u1")

    repo.update_system_settings.assert_called_once_with(settings=new_settings, user_id="u1")
    runtime.invalidate_cache.assert_called_once()
    assert result.max_timeout_seconds == 600


async def test_reset_calls_repo_invalidates_cache_and_reloads() -> None:
    defaults = SystemSettings()
    service, repo, runtime = _make_service()
    runtime.get_effective_settings.return_value = defaults

    result = await service.reset_system_settings("u1")

    repo.reset_system_settings.assert_called_once_with(user_id="u1")
    runtime.invalidate_cache.assert_called_once()
    # After reset, reads fresh from runtime loader
    assert runtime.get_effective_settings.call_count == 1
    assert result.max_timeout_seconds == defaults.max_timeout_seconds


async def test_update_invalidates_before_returning() -> None:
    """Cache invalidation happens so subsequent reads see updated values."""
    service, repo, runtime = _make_service()
    repo.update_system_settings.return_value = SystemSettings()
    calls = MagicMock()
    calls.attach_mock(repo.update_system_settings, "repo_update")
    calls.attach_mock(runtime.invalidate_cache, "invalidate")

    await service.update_system_settings(SystemSettings(), "u1")

    assert [name for name, _, _ in calls.mock_calls] == ["repo_update", "invalidate"]
