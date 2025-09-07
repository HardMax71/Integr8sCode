import pytest
from unittest.mock import AsyncMock

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.domain.admin.settings_models import SystemSettings


pytestmark = pytest.mark.unit


# mock_db fixture now provided by main conftest.py


@pytest.fixture()
def repo(mock_db) -> AdminSettingsRepository:
    return AdminSettingsRepository(mock_db)


@pytest.mark.asyncio
async def test_get_system_settings_creates_default(repo: AdminSettingsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    mock_db.system_settings.find_one = AsyncMock(return_value=None)
    mock_db.system_settings.insert_one = AsyncMock()
    s = await repo.get_system_settings()
    assert isinstance(s, SystemSettings)
    mock_db.system_settings.insert_one.assert_awaited()


@pytest.mark.asyncio
async def test_get_system_settings_existing(repo: AdminSettingsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    # When existing doc present, it should be returned via mapper
    mock_db.system_settings.find_one = AsyncMock(return_value={"_id": "global"})
    s = await repo.get_system_settings()
    assert isinstance(s, SystemSettings)


@pytest.mark.asyncio
async def test_update_and_reset_settings(repo: AdminSettingsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    s = SystemSettings()
    mock_db.system_settings.replace_one = AsyncMock()
    mock_db.audit_log.insert_one = AsyncMock()
    updated = await repo.update_system_settings(s, updated_by="admin", user_id="u1")
    assert isinstance(updated, SystemSettings)
    mock_db.audit_log.insert_one.assert_awaited()

    mock_db.system_settings.delete_one = AsyncMock()
    mock_db.audit_log.insert_one = AsyncMock()
    reset = await repo.reset_system_settings("admin", "u1")
    assert isinstance(reset, SystemSettings)
    mock_db.audit_log.insert_one.assert_awaited()


@pytest.mark.asyncio
async def test_admin_settings_exceptions(repo: AdminSettingsRepository, mock_db: AsyncIOMotorDatabase) -> None:
    s = SystemSettings()
    mock_db.system_settings.replace_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.update_system_settings(s, updated_by="admin", user_id="u1")

    mock_db.system_settings.delete_one = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.reset_system_settings("admin", "u1")
