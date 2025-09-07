import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import IndexModel

from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.domain.user.settings_models import DomainUserSettings
from app.domain.enums.events import EventType


pytestmark = pytest.mark.unit


@pytest.fixture()
def repo(mock_db) -> UserSettingsRepository:
    return UserSettingsRepository(mock_db)


@pytest.mark.asyncio
async def test_create_indexes(repo: UserSettingsRepository, mock_db) -> None:
    mock_db.user_settings_snapshots.create_indexes = AsyncMock()
    mock_db.events.create_indexes = AsyncMock()
    await repo.create_indexes()
    mock_db.user_settings_snapshots.create_indexes.assert_awaited()
    mock_db.events.create_indexes.assert_awaited()


@pytest.mark.asyncio
async def test_snapshot_crud(repo: UserSettingsRepository, mock_db) -> None:
    us = DomainUserSettings(user_id="u1")
    mock_db.user_settings_snapshots.replace_one = AsyncMock()
    await repo.create_snapshot(us)
    mock_db.user_settings_snapshots.replace_one.assert_awaited()

    mock_db.user_settings_snapshots.find_one = AsyncMock(return_value={
        "user_id": "u1",
        "theme": us.theme,
        "timezone": us.timezone,
        "date_format": us.date_format,
        "time_format": us.time_format,
        "notifications": {
            "execution_completed": us.notifications.execution_completed,
            "execution_failed": us.notifications.execution_failed,
            "system_updates": us.notifications.system_updates,
            "security_alerts": us.notifications.security_alerts,
            "channels": us.notifications.channels,
        },
        "editor": {
            "theme": us.editor.theme,
            "font_size": us.editor.font_size,
            "tab_size": us.editor.tab_size,
            "use_tabs": us.editor.use_tabs,
            "word_wrap": us.editor.word_wrap,
            "show_line_numbers": us.editor.show_line_numbers,
        },
        "custom_settings": us.custom_settings,
        "version": us.version,
        # created_at/updated_at may be missing in DB doc; mapper provides defaults
    })
    got = await repo.get_snapshot("u1")
    assert got and got.user_id == "u1"


@pytest.mark.asyncio
async def test_get_settings_events_and_counting(repo: UserSettingsRepository, mock_db) -> None:
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs

    now = datetime.now(timezone.utc)
    docs = [{"event_type": str(EventType.USER_SETTINGS_UPDATED), "timestamp": now, "payload": {}}]
    mock_db.events.find.return_value = Cursor(docs)
    events = await repo.get_settings_events("u1", [EventType.USER_SETTINGS_UPDATED], since=now - timedelta(days=1))
    assert len(events) == 1 and events[0].event_type == EventType.USER_SETTINGS_UPDATED

    # count since snapshot present (include required 'theme' field)
    mock_db.user_settings_snapshots.find_one = AsyncMock(return_value={"user_id": "u1", "theme": "auto"})
    mock_db.events.count_documents = AsyncMock(return_value=2)
    assert await repo.count_events_since_snapshot("u1") == 2

    # count without snapshot
    mock_db.user_settings_snapshots.find_one = AsyncMock(return_value=None)
    mock_db.events.count_documents = AsyncMock(return_value=5)
    assert await repo.count_events_since_snapshot("u2") == 5

    mock_db.events.count_documents = AsyncMock(return_value=9)
    assert await repo.count_events_for_user("u1") == 9


@pytest.mark.asyncio
async def test_create_indexes_exception(repo: UserSettingsRepository, mock_db) -> None:
    mock_db.user_settings_snapshots.create_indexes = AsyncMock(side_effect=Exception("boom"))
    with pytest.raises(Exception):
        await repo.create_indexes()


@pytest.mark.asyncio
async def test_get_settings_events_until_and_limit(repo: UserSettingsRepository, mock_db) -> None:
    # Ensure 'until' and 'limit' branches are exercised
    class Cursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *_a, **_k):
            return self
        def limit(self, *_a, **_k):
            return self
        async def to_list(self, *_a, **_k):
            return self._docs

    now = datetime.now(timezone.utc)
    mock_db.events.find.return_value = Cursor([{ "event_type": str(EventType.USER_SETTINGS_UPDATED), "timestamp": now, "payload": {} }])
    events = await repo.get_settings_events("u1", [EventType.USER_SETTINGS_UPDATED], since=now - timedelta(days=1), until=now, limit=1)
    assert len(events) == 1
