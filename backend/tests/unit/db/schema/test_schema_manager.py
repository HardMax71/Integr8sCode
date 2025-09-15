import asyncio
from typing import Any

import pytest

from app.db.schema.schema_manager import SchemaManager


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_is_applied_and_mark_applied(db) -> None:  # type: ignore[valid-type]
    mgr = SchemaManager(db)
    mig_id = "test_migration_123"
    assert await mgr._is_applied(mig_id) is False
    await mgr._mark_applied(mig_id, "desc")
    assert await mgr._is_applied(mig_id) is True
    doc = await db["schema_versions"].find_one({"_id": mig_id})
    assert doc and doc.get("description") == "desc" and "applied_at" in doc


@pytest.mark.asyncio
async def test_apply_all_idempotent_and_creates_indexes(db) -> None:  # type: ignore[valid-type]
    mgr = SchemaManager(db)
    await mgr.apply_all()
    # Apply again should be a no-op
    await mgr.apply_all()
    versions = await db["schema_versions"].count_documents({})
    assert versions >= 9

    # Verify some expected indexes exist
    async def idx_names(coll: str) -> set[str]:
        lst = await db[coll].list_indexes().to_list(length=None)
        return {i.get("name", "") for i in lst}

    # events
    ev_idx = await idx_names("events")
    assert {"idx_event_id_unique", "idx_event_type_ts", "idx_text_search"}.issubset(ev_idx)
    # user settings
    us_idx = await idx_names("user_settings_snapshots")
    assert {"idx_settings_user_unique", "idx_settings_updated_at_desc"}.issubset(us_idx)
    # replay
    rp_idx = await idx_names("replay_sessions")
    assert {"idx_replay_session_id", "idx_replay_status"}.issubset(rp_idx)
    # notifications
    notif_idx = await idx_names("notifications")
    assert {"idx_notif_user_created_desc", "idx_notif_id_unique"}.issubset(notif_idx)
    subs_idx = await idx_names("notification_subscriptions")
    assert {"idx_sub_user_channel_unique", "idx_sub_enabled"}.issubset(subs_idx)
    # idempotency
    idem_idx = await idx_names("idempotency_keys")
    assert {"idx_idem_key_unique", "idx_idem_created_ttl"}.issubset(idem_idx)
    # sagas
    saga_idx = await idx_names("sagas")
    assert {"idx_saga_id_unique", "idx_saga_state_created"}.issubset(saga_idx)
    # execution_results
    res_idx = await idx_names("execution_results")
    assert {"idx_results_execution_unique", "idx_results_created_at"}.issubset(res_idx)
    # dlq
    dlq_idx = await idx_names("dlq_messages")
    assert {"idx_dlq_event_id_unique", "idx_dlq_failed_desc"}.issubset(dlq_idx)


class _StubColl:
    def __init__(self, raise_on_create: bool = False) -> None:
        self.raise_on_create = raise_on_create
        self.created: list[Any] = []

    async def create_indexes(self, indexes: list[Any]) -> None:
        if self.raise_on_create:
            raise RuntimeError("boom")
        self.created.extend(indexes)

    # Minimal API for versions collection in __init__
    async def find_one(self, q: dict) -> dict | None:  # type: ignore[override]
        return None

    async def update_one(self, *args, **kwargs) -> None:  # type: ignore[override]
        return None


class _StubDB:
    def __init__(self, fail_collections: set[str] | None = None, fail_command: bool = False) -> None:
        self._fails = fail_collections or set()
        self._fail_cmd = fail_command
        self._colls: dict[str, _StubColl] = {}

    def __getitem__(self, name: str) -> _StubColl:
        if name not in self._colls:
            self._colls[name] = _StubColl(raise_on_create=(name in self._fails))
        return self._colls[name]

    async def command(self, *_args, **_kwargs) -> None:
        if self._fail_cmd:
            raise RuntimeError("cmd_fail")
        return None


@pytest.mark.asyncio
async def test_migrations_handle_exceptions_gracefully() -> None:
    # Fail events.create_indexes and db.command
    stub = _StubDB(fail_collections={"events"}, fail_command=True)
    mgr = SchemaManager(stub)  # type: ignore[arg-type]
    # Call individual migrations; they should not raise
    await mgr._m_0001_events_init()
    await mgr._m_0002_user_settings()
    await mgr._m_0003_replay()
    await mgr._m_0004_notifications()
    await mgr._m_0005_idempotency()
    await mgr._m_0006_sagas()
    await mgr._m_0007_execution_results()
    await mgr._m_0008_dlq()
    await mgr._m_0009_event_store_extra()


@pytest.mark.asyncio
async def test_apply_all_skips_already_applied(db) -> None:  # type: ignore[valid-type]
    mgr = SchemaManager(db)
    # Mark first migration as applied
    await db["schema_versions"].insert_one({"_id": "0001_events_init"})
    await mgr.apply_all()
    # Ensure we have all migrations recorded and no duplicates
    count = await db["schema_versions"].count_documents({})
    assert count >= 9
