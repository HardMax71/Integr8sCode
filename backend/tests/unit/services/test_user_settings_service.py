from datetime import datetime, timezone

import pytest

from app.domain.enums import Theme
from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainUserSettingsUpdate,
)
from app.services.user_settings_service import UserSettingsService


@pytest.mark.asyncio
async def test_get_update_and_history(scope) -> None:  # type: ignore[valid-type]
    svc: UserSettingsService = await scope.get(UserSettingsService)
    user_id = "u1"

    s1 = await svc.get_user_settings(user_id)
    s2 = await svc.get_user_settings(user_id)
    assert s1.user_id == s2.user_id
    svc.invalidate_cache(user_id)
    s3 = await svc.get_user_settings(user_id)
    assert s3.user_id == user_id

    updates = DomainUserSettingsUpdate(theme=Theme.DARK, notifications=DomainNotificationSettings(),
                                       editor=DomainEditorSettings(tab_size=4))
    updated = await svc.update_user_settings(user_id, updates, reason="r")
    assert updated.theme == Theme.DARK

    hist = await svc.get_settings_history(user_id)
    assert isinstance(hist, list)

    # Restore to current point (no-op but tests snapshot + event publish path)
    _ = await svc.restore_settings_to_point(user_id, datetime.now(timezone.utc))

    # Update wrappers + cache stats
    await svc.update_theme(user_id, Theme.DARK)
    await svc.update_notification_settings(user_id, DomainNotificationSettings())
    await svc.update_editor_settings(user_id, DomainEditorSettings(tab_size=2))
    await svc.update_custom_setting(user_id, "k", "v")
    stats = svc.get_cache_stats()
    assert stats["cache_size"] >= 1
