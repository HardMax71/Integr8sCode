import pytest
from app.db.docs import AuditLogDocument
from app.db.repositories import AdminSettingsRepository
from app.domain.admin import SystemSettings
from dishka import AsyncContainer

pytestmark = pytest.mark.e2e


@pytest.fixture()
async def repo(scope: AsyncContainer) -> AdminSettingsRepository:
    return await scope.get(AdminSettingsRepository)


@pytest.mark.asyncio
async def test_get_system_settings_creates_default(repo: AdminSettingsRepository) -> None:
    s = await repo.get_system_settings()
    assert isinstance(s, SystemSettings)


@pytest.mark.asyncio
async def test_get_system_settings_existing(repo: AdminSettingsRepository) -> None:
    s1 = await repo.get_system_settings()
    s2 = await repo.get_system_settings()
    assert isinstance(s1, SystemSettings) and isinstance(s2, SystemSettings)


@pytest.mark.asyncio
async def test_update_and_reset_settings(repo: AdminSettingsRepository) -> None:
    s = SystemSettings()
    updated = await repo.update_system_settings(s, updated_by="admin", user_id="u1")
    assert isinstance(updated, SystemSettings)
    # verify audit log entry exists using Beanie ODM
    assert await AuditLogDocument.count() >= 1
    reset = await repo.reset_system_settings("admin", "u1")
    assert isinstance(reset, SystemSettings)
    assert await AuditLogDocument.count() >= 2
