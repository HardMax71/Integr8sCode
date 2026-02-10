import pytest
from app.db.docs import AuditLogDocument
from app.db.repositories import AdminSettingsRepository
from app.domain.admin import SystemSettings
from dishka import AsyncContainer

pytestmark = pytest.mark.e2e

_DEFAULTS = SystemSettings()


@pytest.fixture()
async def repo(scope: AsyncContainer) -> AdminSettingsRepository:
    return await scope.get(AdminSettingsRepository)


@pytest.mark.asyncio
async def test_get_system_settings_creates_default(repo: AdminSettingsRepository) -> None:
    s = await repo.get_system_settings(defaults=_DEFAULTS)
    assert isinstance(s, SystemSettings)


@pytest.mark.asyncio
async def test_get_system_settings_existing(repo: AdminSettingsRepository) -> None:
    s1 = await repo.get_system_settings(defaults=_DEFAULTS)
    s2 = await repo.get_system_settings(defaults=_DEFAULTS)
    assert isinstance(s1, SystemSettings) and isinstance(s2, SystemSettings)


@pytest.mark.asyncio
async def test_get_seeds_with_provided_defaults(repo: AdminSettingsRepository) -> None:
    await repo.reset_system_settings("test", "test")
    custom = SystemSettings(max_timeout_seconds=777, memory_limit="1024Mi")
    s = await repo.get_system_settings(defaults=custom)
    assert s.max_timeout_seconds == 777
    assert s.memory_limit == "1024Mi"


@pytest.mark.asyncio
async def test_update_persists_values(repo: AdminSettingsRepository) -> None:
    updated_settings = SystemSettings(max_timeout_seconds=42, cpu_limit="500m")
    result = await repo.update_system_settings(updated_settings, updated_by="admin", user_id="u1")
    assert result.max_timeout_seconds == 42
    assert result.cpu_limit == "500m"

    reloaded = await repo.get_system_settings(defaults=_DEFAULTS)
    assert reloaded.max_timeout_seconds == 42


@pytest.mark.asyncio
async def test_update_creates_audit_log(repo: AdminSettingsRepository) -> None:
    count_before = await AuditLogDocument.count()
    await repo.update_system_settings(SystemSettings(), updated_by="admin", user_id="u1")
    assert await AuditLogDocument.count() > count_before


@pytest.mark.asyncio
async def test_reset_deletes_doc_and_returns_defaults(repo: AdminSettingsRepository) -> None:
    await repo.update_system_settings(
        SystemSettings(max_timeout_seconds=999),
        updated_by="admin",
        user_id="u1",
    )
    result = await repo.reset_system_settings("admin", "u1")
    assert result.max_timeout_seconds == _DEFAULTS.max_timeout_seconds


@pytest.mark.asyncio
async def test_reset_creates_audit_log(repo: AdminSettingsRepository) -> None:
    count_before = await AuditLogDocument.count()
    await repo.reset_system_settings("admin", "u1")
    assert await AuditLogDocument.count() > count_before
