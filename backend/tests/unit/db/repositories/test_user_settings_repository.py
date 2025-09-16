from datetime import datetime, timezone, timedelta

import pytest

from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.domain.enums.events import EventType
from app.domain.user.settings_models import DomainUserSettings

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_user_settings_snapshot_and_events(db) -> None:  # type: ignore[valid-type]
    repo = UserSettingsRepository(db)

    # Create indexes (should not raise)
    await repo.create_indexes()

    # Snapshot CRUD
    us = DomainUserSettings(user_id="u1")
    await repo.create_snapshot(us)
    got = await repo.get_snapshot("u1")
    assert got and got.user_id == "u1"

    # Insert events and query
    now = datetime.now(timezone.utc)
    await db.get_collection("events").insert_many([
        {
            "aggregate_id": "user_settings_u1",
            "event_type": str(EventType.USER_SETTINGS_UPDATED),
            "timestamp": now,
            "payload": {}
        },
        {
            "aggregate_id": "user_settings_u1",
            "event_type": str(EventType.USER_THEME_CHANGED),
            "timestamp": now,
            "payload": {}
        },
    ])
    evs = await repo.get_settings_events("u1", [EventType.USER_SETTINGS_UPDATED], since=now - timedelta(days=1))
    assert any(e.event_type == EventType.USER_SETTINGS_UPDATED for e in evs)

    # Counting helpers
    assert await repo.count_events_for_user("u1") >= 2
    assert await repo.count_events_since_snapshot("u1") >= 0
