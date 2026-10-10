import asyncio

import pytest
from dishka import AsyncContainer

from app.db.docs import AuditLogDocument, SystemSettingsDocument
from app.db.repositories import AdminSettingsRepository
from app.domain.admin import SystemSettings
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.xdist_group("system_settings")]


@pytest.fixture()
async def repo(scope: AsyncContainer) -> AdminSettingsRepository:
    return await scope.get(AdminSettingsRepository)


@pytest.fixture()
def toml_defaults(test_settings: Settings) -> SystemSettings:
    # RuntimeSettingsLoader seeds these same values, so a concurrent reseed can't change the outcome.
    return SystemSettings(
        max_timeout_seconds=test_settings.K8S_POD_EXECUTION_TIMEOUT,
        memory_limit=test_settings.K8S_POD_MEMORY_LIMIT,
        cpu_limit=test_settings.K8S_POD_CPU_LIMIT,
        session_timeout_minutes=test_settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )


@pytest.mark.asyncio
async def test_get_system_settings_creates_default(
    repo: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    s = await repo.get_system_settings(defaults=toml_defaults)
    assert isinstance(s, SystemSettings)


@pytest.mark.asyncio
async def test_get_system_settings_existing(repo: AdminSettingsRepository, toml_defaults: SystemSettings) -> None:
    s1 = await repo.get_system_settings(defaults=toml_defaults)
    s2 = await repo.get_system_settings(defaults=toml_defaults)
    assert isinstance(s1, SystemSettings) and isinstance(s2, SystemSettings)


@pytest.mark.asyncio
async def test_get_seeds_with_provided_defaults(repo: AdminSettingsRepository, toml_defaults: SystemSettings) -> None:
    assert toml_defaults != SystemSettings()
    await repo.reset_system_settings(user_id="test")
    s = await repo.get_system_settings(defaults=toml_defaults)
    assert s == toml_defaults


@pytest.mark.asyncio
async def test_update_persists_values(repo: AdminSettingsRepository, toml_defaults: SystemSettings) -> None:
    updated_settings = SystemSettings(max_timeout_seconds=42, cpu_limit="500m")
    result = await repo.update_system_settings(updated_settings, user_id="u1")
    assert result.max_timeout_seconds == 42
    assert result.cpu_limit == "500m"

    reloaded = await repo.get_system_settings(defaults=toml_defaults)
    assert reloaded.max_timeout_seconds == 42


@pytest.mark.asyncio
async def test_update_creates_audit_log(repo: AdminSettingsRepository, toml_defaults: SystemSettings) -> None:
    count_before = await AuditLogDocument.count()
    await repo.update_system_settings(toml_defaults, user_id="u1")
    assert await AuditLogDocument.count() > count_before


@pytest.mark.asyncio
async def test_reset_deletes_doc_and_returns_defaults(repo: AdminSettingsRepository) -> None:
    await repo.update_system_settings(SystemSettings(max_timeout_seconds=999), user_id="u1")
    result = await repo.reset_system_settings(user_id="u1")
    assert result == SystemSettings()


@pytest.mark.asyncio
async def test_reset_creates_audit_log(repo: AdminSettingsRepository) -> None:
    count_before = await AuditLogDocument.count()
    await repo.reset_system_settings(user_id="u1")
    assert await AuditLogDocument.count() > count_before


@pytest.mark.asyncio
async def test_settings_id_has_unique_index() -> None:
    indexes = await SystemSettingsDocument.get_pymongo_collection().index_information()
    assert any(index.get("unique") and index["key"] == [("settings_id", 1)] for index in indexes.values())


@pytest.mark.asyncio
async def test_concurrent_first_reads_create_one_document(
    repo: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").delete()
    # Warm the connection pool, otherwise the first reads queue on one connection and never overlap.
    await asyncio.gather(*(SystemSettingsDocument.find_one({"settings_id": "-"}) for _ in range(20)))

    results = await asyncio.gather(*(repo.get_system_settings(defaults=toml_defaults) for _ in range(20)))

    assert all(result == toml_defaults for result in results)
    assert await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").count() == 1


@pytest.mark.asyncio
async def test_update_racing_first_read_keeps_one_document(
    repo: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").delete()
    updated = SystemSettings(max_timeout_seconds=42)

    await asyncio.gather(
        repo.update_system_settings(updated, user_id="test"),
        *(repo.get_system_settings(defaults=toml_defaults) for _ in range(10)),
    )

    assert await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").count() == 1
    assert await repo.get_system_settings(defaults=toml_defaults) == updated
