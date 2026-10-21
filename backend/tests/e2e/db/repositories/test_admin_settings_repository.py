import asyncio
import dataclasses
from collections.abc import AsyncIterator

import pytest

from app.db.docs import AuditLogDocument, SystemSettingsDocument
from app.db.repositories import AdminSettingsRepository
from app.domain.admin import SystemSettings
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.xdist_group("system_settings")]


@pytest.fixture(autouse=True)
async def _drop_global_settings(admin_settings_repository: AdminSettingsRepository) -> AsyncIterator[None]:
    # Every process reads these settings, so tests change only the lockout duration and leave the TOML defaults behind
    yield
    await admin_settings_repository.reset_system_settings(user_id="test")


@pytest.fixture()
def toml_defaults(test_settings: Settings) -> SystemSettings:
    # RuntimeSettingsLoader seeds these same values, so a concurrent reseed can't change the outcome.
    return SystemSettings(
        max_timeout_seconds=test_settings.K8S_POD_EXECUTION_TIMEOUT,
        memory_limit=test_settings.K8S_POD_MEMORY_LIMIT,
        cpu_limit=test_settings.K8S_POD_CPU_LIMIT,
        session_timeout_minutes=test_settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )


async def test_get_system_settings_creates_default(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    s = await admin_settings_repository.get_system_settings(defaults=toml_defaults)
    assert isinstance(s, SystemSettings)


async def test_get_system_settings_existing(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    s1 = await admin_settings_repository.get_system_settings(defaults=toml_defaults)
    s2 = await admin_settings_repository.get_system_settings(defaults=toml_defaults)
    assert isinstance(s1, SystemSettings) and isinstance(s2, SystemSettings)


async def test_get_seeds_with_provided_defaults(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    assert toml_defaults != SystemSettings()
    await admin_settings_repository.reset_system_settings(user_id="test")
    s = await admin_settings_repository.get_system_settings(defaults=toml_defaults)
    assert s == toml_defaults


async def test_update_persists_values(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    updated = dataclasses.replace(toml_defaults, lockout_duration_minutes=42)
    assert await admin_settings_repository.update_system_settings(updated, user_id="u1") == updated
    assert await admin_settings_repository.get_system_settings(defaults=toml_defaults) == updated


async def test_update_creates_audit_log(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    count_before = await AuditLogDocument.count()
    await admin_settings_repository.update_system_settings(toml_defaults, user_id="u1")
    assert await AuditLogDocument.count() > count_before


async def test_reset_deletes_doc_and_returns_defaults(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    await admin_settings_repository.update_system_settings(
        dataclasses.replace(toml_defaults, lockout_duration_minutes=60), user_id="u1"
    )
    result = await admin_settings_repository.reset_system_settings(user_id="u1")
    assert result == SystemSettings()


async def test_reset_creates_audit_log(admin_settings_repository: AdminSettingsRepository) -> None:
    count_before = await AuditLogDocument.count()
    await admin_settings_repository.reset_system_settings(user_id="u1")
    assert await AuditLogDocument.count() > count_before


async def test_settings_id_has_unique_index() -> None:
    indexes = await SystemSettingsDocument.get_pymongo_collection().index_information()
    assert any(index.get("unique") and index["key"] == [("settings_id", 1)] for index in indexes.values())


async def test_concurrent_first_reads_create_one_document(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").delete()
    # Warm the connection pool, otherwise the first reads queue on one connection and never overlap.
    await asyncio.gather(*(SystemSettingsDocument.find_one({"settings_id": "-"}) for _ in range(20)))

    results = await asyncio.gather(
        *(admin_settings_repository.get_system_settings(defaults=toml_defaults) for _ in range(20))
    )

    assert all(result == toml_defaults for result in results)
    assert await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").count() == 1


async def test_update_racing_first_read_keeps_one_document(
    admin_settings_repository: AdminSettingsRepository, toml_defaults: SystemSettings
) -> None:
    await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").delete()
    updated = dataclasses.replace(toml_defaults, lockout_duration_minutes=42)

    await asyncio.gather(
        admin_settings_repository.update_system_settings(updated, user_id="test"),
        *(admin_settings_repository.get_system_settings(defaults=toml_defaults) for _ in range(10)),
    )

    assert await SystemSettingsDocument.find(SystemSettingsDocument.settings_id == "global").count() == 1
    assert await admin_settings_repository.get_system_settings(defaults=toml_defaults) == updated
