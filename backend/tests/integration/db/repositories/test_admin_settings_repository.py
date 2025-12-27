import pytest

from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.domain.admin import SystemSettings

pytestmark = pytest.mark.integration


@pytest.fixture()
def repo(db) -> AdminSettingsRepository:  # type: ignore[valid-type]
    return AdminSettingsRepository(db)


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
async def test_update_and_reset_settings(repo: AdminSettingsRepository, db) -> None:  # type: ignore[valid-type]
    s = SystemSettings()
    updated = await repo.update_system_settings(s, updated_by="admin", user_id="u1")
    assert isinstance(updated, SystemSettings)
    # verify audit log entry exists
    assert await db.get_collection("audit_log").count_documents({}) >= 1
    reset = await repo.reset_system_settings("admin", "u1")
    assert isinstance(reset, SystemSettings)
    assert await db.get_collection("audit_log").count_documents({}) >= 2
