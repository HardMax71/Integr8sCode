import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.domain.enums.events import EventType
from app.domain.enums import Theme
from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsEvent,
    DomainUserSettings,
    DomainUserSettingsUpdate,
)
from app.services.user_settings_service import UserSettingsService


class FakeRepo:
    def __init__(self, snap=None, events=None):  # noqa: ANN001
        self.snap = snap
        self.events = events or []
        self.snapshots = []
        self.count = 0
    async def get_snapshot(self, user_id):  # noqa: ANN001
        return self.snap
    async def get_settings_events(self, **kwargs):  # noqa: ANN001
        return self.events
    async def count_events_since_snapshot(self, user_id):  # noqa: ANN001
        self.count += 1
        return 10
    async def create_snapshot(self, settings):  # noqa: ANN001
        self.snapshots.append(settings)


class FakeEventSvc:
    def __init__(self):
        self.calls = []
    async def publish_event(self, **kwargs):  # noqa: ANN001
        self.calls.append(kwargs)


class SimpleUser:
    def __init__(self, user_id: str):
        self.user_id = user_id

def mk_user():
    return SimpleUser(user_id="u1")


def mk_event(event_type, changes):  # noqa: ANN001
    return DomainSettingsEvent(
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        correlation_id="c",
        payload={"changes": changes, "new_values": {"theme": Theme.DARK, "editor": {"tab_size": 2}, "notifications": {"execution_completed": True}}},
    )


@pytest.mark.asyncio
async def test_get_user_settings_cache_and_fresh():
    repo = FakeRepo(snap=None, events=[])
    svc = UserSettingsService(repository=repo, event_service=FakeEventSvc())
    s1 = await svc.get_user_settings("u1")
    s2 = await svc.get_user_settings("u1")
    assert s1.user_id == s2.user_id
    # Invalidate
    svc.invalidate_cache("u1")
    s3 = await svc.get_user_settings("u1")
    assert s3.user_id == "u1"


@pytest.mark.asyncio
async def test_update_user_settings_and_event_type_mapping():
    repo = FakeRepo(snap=DomainUserSettings(user_id="u1"), events=[])
    evs = FakeEventSvc()
    svc = UserSettingsService(repository=repo, event_service=evs)
    user = mk_user()
    updates = DomainUserSettingsUpdate(theme=Theme.DARK, notifications=DomainNotificationSettings(), editor=DomainEditorSettings(tab_size=4))
    updated = await svc.update_user_settings(user.user_id, updates, reason="r")
    assert updated.theme == Theme.DARK
    assert evs.calls
    types = [c["event_type"] for c in evs.calls]
    assert EventType.USER_SETTINGS_UPDATED in types or EventType.USER_THEME_CHANGED in types


@pytest.mark.asyncio
async def test_get_settings_history_from_events():
    ts = datetime.now(timezone.utc)
    ev = mk_event(EventType.USER_SETTINGS_UPDATED, [{"field_path": "theme", "old_value": Theme.AUTO, "new_value": Theme.DARK}])
    repo = FakeRepo(events=[ev])
    svc = UserSettingsService(repository=repo, event_service=FakeEventSvc())
    hist = await svc.get_settings_history("u1")
    assert hist and hist[0].field == "theme"


def test_apply_event_variants():
    svc = UserSettingsService(repository=FakeRepo(), event_service=FakeEventSvc())
    base = DomainUserSettings(user_id="u1")
    # Theme changed
    e_theme = mk_event(EventType.USER_THEME_CHANGED, [])
    new1 = svc._apply_event(base, e_theme)
    assert new1.theme == Theme.DARK
    # Notifications
    e_notif = mk_event(EventType.USER_NOTIFICATION_SETTINGS_UPDATED, [])
    new2 = svc._apply_event(base, e_notif)
    assert isinstance(new2.notifications, DomainNotificationSettings)
    # Editor
    e_editor = mk_event(EventType.USER_EDITOR_SETTINGS_UPDATED, [])
    new3 = svc._apply_event(base, e_editor)
    assert isinstance(new3.editor, DomainEditorSettings)
    # Generic nested change via dot path
    e_generic = DomainSettingsEvent(
        event_type=EventType.USER_SETTINGS_UPDATED,
        timestamp=datetime.now(timezone.utc),
        correlation_id="c",
        payload={"changes": [{"field_path": "editor.tab_size", "old_value": 2, "new_value": 4}]},
    )
    new4 = svc._apply_event(base, e_generic)
    assert new4.editor.tab_size == 4


@pytest.mark.asyncio
async def test_restore_settings_to_point_creates_snapshot_and_publishes():
    ev = mk_event(EventType.USER_SETTINGS_UPDATED, [])
    repo = FakeRepo(events=[ev])
    evs = FakeEventSvc()
    svc = UserSettingsService(repository=repo, event_service=evs)
    user = mk_user()
    restored = await svc.restore_settings_to_point(user.user_id, datetime.now(timezone.utc))
    assert repo.snapshots and repo.snapshots[0].user_id == user.user_id
    assert evs.calls and evs.calls[-1]["event_type"] == EventType.USER_SETTINGS_UPDATED


@pytest.mark.asyncio
async def test_update_wrappers_and_cache_eviction():
    repo = FakeRepo(snap=DomainUserSettings(user_id="u1"), events=[])
    evs = FakeEventSvc()
    svc = UserSettingsService(repository=repo, event_service=evs)
    user = mk_user()
    await svc.update_theme(user.user_id, Theme.DARK)
    await svc.update_notification_settings(user.user_id, DomainNotificationSettings())
    await svc.update_editor_settings(user.user_id, DomainEditorSettings(tab_size=2))
    await svc.update_custom_setting(user.user_id, "k", "v")
    # Cache eviction
    svc._max_cache_size = 1
    svc._add_to_cache("u1", DomainUserSettings(user_id="u1"))
    svc._add_to_cache("u2", DomainUserSettings(user_id="u2"))
    stats = svc.get_cache_stats()
    assert stats["cache_size"] == 1
    # Expiry cleanup
    svc._settings_cache.clear()
    from datetime import datetime, timedelta, timezone
    svc._settings_cache["u3"] = type("C", (), {"settings": DomainUserSettings(user_id="u3"), "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})()
    svc._cleanup_expired_cache()
    assert "u3" not in svc._settings_cache


def test_determine_event_type_from_fields():
    svc = UserSettingsService(repository=FakeRepo(), event_service=FakeEventSvc())
    assert svc._determine_event_type_from_fields({"theme"}) == EventType.USER_THEME_CHANGED
    assert svc._determine_event_type_from_fields({"notifications"}) == EventType.USER_NOTIFICATION_SETTINGS_UPDATED
    # default
    assert svc._determine_event_type_from_fields({"a", "b"}) == EventType.USER_SETTINGS_UPDATED
