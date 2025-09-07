import pytest
from unittest.mock import AsyncMock

from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection

from app.db.schema.schema_manager import SchemaManager


pytestmark = pytest.mark.unit


@pytest.fixture()
def mock_db() -> AsyncMock:
    db = AsyncMock(spec=AsyncIOMotorDatabase)
    # collections used by migrations
    names = [
        "schema_versions", "events", "user_settings_snapshots", "events", "replay_sessions",
        "notifications", "notification_rules", "notification_subscriptions",
        "idempotency_keys", "sagas", "execution_results", "dlq_messages"
    ]
    for n in set(names):
        setattr(db, n, AsyncMock(spec=AsyncIOMotorCollection))
    # __getitem__ access for schema_versions and others
    db.__getitem__.side_effect = lambda name: getattr(db, name)
    db.command = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_apply_all_runs_migrations_and_marks_applied(mock_db: AsyncIOMotorDatabase) -> None:
    mgr = SchemaManager(mock_db)
    # none applied
    mock_db.schema_versions.find_one = AsyncMock(return_value=None)
    # Set up update_one as AsyncMock for schema_versions
    mock_db.schema_versions.update_one = AsyncMock()
    # allow create_indexes on all
    for attr in dir(mock_db):
        coll = getattr(mock_db, attr)
        if isinstance(coll, AsyncMock) and hasattr(coll, "create_indexes"):
            coll.create_indexes = AsyncMock()
    await mgr.apply_all()
    # should have marked each migration
    assert mock_db.schema_versions.update_one.await_count >= 1


@pytest.mark.asyncio
async def test_migration_handles_index_and_validator_errors(mock_db: AsyncIOMotorDatabase) -> None:
    mgr = SchemaManager(mock_db)
    # _is_applied false then run only first migration and cause exceptions
    mock_db.schema_versions.find_one = AsyncMock(return_value=None)
    # events.create_indexes raises
    mock_db.events.create_indexes = AsyncMock(side_effect=Exception("boom"))
    # db.command (validator) raises
    mock_db.command = AsyncMock(side_effect=Exception("cmd fail"))
    # limit migrations to first one by mocking apply_all to call only _m_0001
    await mgr._m_0001_events_init()
    # no exception propagates
    assert True

