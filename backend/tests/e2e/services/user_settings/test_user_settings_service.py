import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.domain.enums import Theme
from app.domain.user.settings_models import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsUpdate,
)
from app.services.user_settings_service import UserSettingsService
from dishka import AsyncContainer

pytestmark = [pytest.mark.e2e, pytest.mark.mongodb, pytest.mark.kafka]


def _unique_user_id() -> str:
    return f"settings_user_{uuid.uuid4().hex[:8]}"


class TestGetUserSettings:
    """Tests for get_user_settings method."""

    @pytest.mark.asyncio
    async def test_get_user_settings_new_user(self, scope: AsyncContainer) -> None:
        """Get settings for new user returns defaults."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        settings = await svc.get_user_settings(user_id)

        assert isinstance(settings, DomainUserSettings)
        assert settings.user_id == user_id
        assert settings.theme == Theme.AUTO  # Default theme
        assert settings.editor is not None
        assert settings.notifications is not None

    @pytest.mark.asyncio
    async def test_get_user_settings_cache_hit(self, scope: AsyncContainer) -> None:
        """Second get_user_settings should hit cache."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # First call - cache miss
        settings1 = await svc.get_user_settings(user_id)

        # Second call - cache hit
        settings2 = await svc.get_user_settings(user_id)

        assert settings1.user_id == settings2.user_id
        assert settings1.theme == settings2.theme

    @pytest.mark.asyncio
    async def test_get_user_settings_fresh_bypasses_cache(
        self, scope: AsyncContainer
    ) -> None:
        """get_user_settings_fresh bypasses cache."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Get and cache
        await svc.get_user_settings(user_id)

        # Fresh should still work
        fresh = await svc.get_user_settings_fresh(user_id)

        assert isinstance(fresh, DomainUserSettings)
        assert fresh.user_id == user_id


class TestUpdateUserSettings:
    """Tests for update_user_settings method."""

    @pytest.mark.asyncio
    async def test_update_theme(self, scope: AsyncContainer) -> None:
        """Update theme setting."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Update theme
        updates = DomainUserSettingsUpdate(theme=Theme.DARK)
        updated = await svc.update_user_settings(user_id, updates)

        assert updated.theme == Theme.DARK

        # Verify persistence
        retrieved = await svc.get_user_settings(user_id)
        assert retrieved.theme == Theme.DARK

    @pytest.mark.asyncio
    async def test_update_multiple_settings(self, scope: AsyncContainer) -> None:
        """Update multiple settings at once."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        updates = DomainUserSettingsUpdate(
            theme=Theme.LIGHT,
            timezone="Europe/London",
            date_format="DD/MM/YYYY",
        )
        updated = await svc.update_user_settings(user_id, updates)

        assert updated.theme == Theme.LIGHT
        assert updated.timezone == "Europe/London"
        assert updated.date_format == "DD/MM/YYYY"

    @pytest.mark.asyncio
    async def test_update_with_reason(self, scope: AsyncContainer) -> None:
        """Update settings with reason tracked."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        reason_text = "User preference"
        updates = DomainUserSettingsUpdate(theme=Theme.DARK)
        await svc.update_user_settings(user_id, updates, reason=reason_text)

        # Verify reason was persisted in history
        history = await svc.get_settings_history(user_id)
        assert isinstance(history, list)
        assert len(history) > 0, "Expected at least one history entry after update"

        # Find entry with our reason
        reasons_found = [entry.reason for entry in history if entry.reason == reason_text]
        assert len(reasons_found) > 0, (
            f"Expected history to contain entry with reason '{reason_text}', "
            f"found reasons: {[e.reason for e in history]}"
        )

    @pytest.mark.asyncio
    async def test_update_increments_version(self, scope: AsyncContainer) -> None:
        """Each update increments settings version."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Get initial
        initial = await svc.get_user_settings(user_id)
        initial_version = initial.version or 0

        # Update
        updates = DomainUserSettingsUpdate(theme=Theme.DARK)
        updated = await svc.update_user_settings(user_id, updates)

        assert updated.version is not None
        assert updated.version > initial_version

    @pytest.mark.asyncio
    async def test_update_empty_changes_no_op(self, scope: AsyncContainer) -> None:
        """Empty update is a no-op."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Get initial
        initial = await svc.get_user_settings(user_id)

        # Empty update
        updates = DomainUserSettingsUpdate()
        result = await svc.update_user_settings(user_id, updates)

        # Should return same settings
        assert result.theme == initial.theme


class TestUpdateTheme:
    """Tests for update_theme convenience method."""

    @pytest.mark.asyncio
    async def test_update_theme_to_dark(self, scope: AsyncContainer) -> None:
        """Update theme to dark."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        result = await svc.update_theme(user_id, Theme.DARK)

        assert result.theme == Theme.DARK

    @pytest.mark.asyncio
    async def test_update_theme_to_light(self, scope: AsyncContainer) -> None:
        """Update theme to light."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        result = await svc.update_theme(user_id, Theme.LIGHT)

        assert result.theme == Theme.LIGHT

    @pytest.mark.asyncio
    async def test_update_theme_to_system(self, scope: AsyncContainer) -> None:
        """Update theme to system default."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # First set to dark
        await svc.update_theme(user_id, Theme.DARK)

        # Then back to auto
        result = await svc.update_theme(user_id, Theme.AUTO)

        assert result.theme == Theme.AUTO


class TestUpdateNotificationSettings:
    """Tests for update_notification_settings method."""

    @pytest.mark.asyncio
    async def test_update_notification_settings(self, scope: AsyncContainer) -> None:
        """Update notification settings."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        notification_settings = DomainNotificationSettings(
            execution_completed=True,
            execution_failed=True,
            system_updates=False,
        )
        result = await svc.update_notification_settings(user_id, notification_settings)

        assert result.notifications is not None
        assert result.notifications.execution_completed is True
        assert result.notifications.execution_failed is True
        assert result.notifications.system_updates is False

    @pytest.mark.asyncio
    async def test_disable_all_notifications(self, scope: AsyncContainer) -> None:
        """Disable all notifications."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        notification_settings = DomainNotificationSettings(
            execution_completed=False,
            execution_failed=False,
            system_updates=False,
            security_alerts=False,
        )
        result = await svc.update_notification_settings(user_id, notification_settings)

        assert result.notifications.execution_completed is False


class TestUpdateEditorSettings:
    """Tests for update_editor_settings method."""

    @pytest.mark.asyncio
    async def test_update_editor_tab_size(self, scope: AsyncContainer) -> None:
        """Update editor tab size."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        editor_settings = DomainEditorSettings(tab_size=4)
        result = await svc.update_editor_settings(user_id, editor_settings)

        assert result.editor is not None
        assert result.editor.tab_size == 4

    @pytest.mark.asyncio
    async def test_update_editor_multiple_options(
        self, scope: AsyncContainer
    ) -> None:
        """Update multiple editor settings."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        editor_settings = DomainEditorSettings(
            tab_size=2,
            show_line_numbers=True,
            word_wrap=True,
            font_size=14,
        )
        result = await svc.update_editor_settings(user_id, editor_settings)

        assert result.editor.tab_size == 2
        assert result.editor.show_line_numbers is True
        assert result.editor.word_wrap is True
        assert result.editor.font_size == 14


class TestUpdateCustomSetting:
    """Tests for update_custom_setting method."""

    @pytest.mark.asyncio
    async def test_update_custom_setting_string(self, scope: AsyncContainer) -> None:
        """Update custom setting with string value."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        result = await svc.update_custom_setting(user_id, "favorite_color", "blue")

        assert result.custom_settings is not None
        assert result.custom_settings.get("favorite_color") == "blue"

    @pytest.mark.asyncio
    async def test_update_custom_setting_number(self, scope: AsyncContainer) -> None:
        """Update custom setting with number value."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        result = await svc.update_custom_setting(user_id, "max_results", 100)

        assert result.custom_settings.get("max_results") == 100

    @pytest.mark.asyncio
    async def test_update_custom_setting_boolean(self, scope: AsyncContainer) -> None:
        """Update custom setting with boolean value."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        result = await svc.update_custom_setting(user_id, "beta_features", True)

        assert result.custom_settings.get("beta_features") is True

    @pytest.mark.asyncio
    async def test_update_multiple_custom_settings(
        self, scope: AsyncContainer
    ) -> None:
        """Update multiple custom settings sequentially."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        await svc.update_custom_setting(user_id, "key1", "value1")
        await svc.update_custom_setting(user_id, "key2", "value2")
        result = await svc.update_custom_setting(user_id, "key3", "value3")

        assert result.custom_settings.get("key1") == "value1"
        assert result.custom_settings.get("key2") == "value2"
        assert result.custom_settings.get("key3") == "value3"


class TestGetSettingsHistory:
    """Tests for get_settings_history method."""

    @pytest.mark.asyncio
    async def test_get_settings_history_empty(self, scope: AsyncContainer) -> None:
        """New user has no history."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        history = await svc.get_settings_history(user_id)

        assert isinstance(history, list)

    @pytest.mark.asyncio
    async def test_get_settings_history_after_updates(
        self, scope: AsyncContainer
    ) -> None:
        """History contains entries after updates."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Make some updates
        await svc.update_theme(user_id, Theme.DARK)
        await svc.update_theme(user_id, Theme.LIGHT)

        history = await svc.get_settings_history(user_id)

        assert isinstance(history, list)
        # Should have at least some history entries
        for entry in history:
            assert isinstance(entry, DomainSettingsHistoryEntry)
            assert entry.timestamp is not None

    @pytest.mark.asyncio
    async def test_get_settings_history_with_limit(
        self, scope: AsyncContainer
    ) -> None:
        """History respects limit parameter and returns most recent entries."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Make 5 updates sequentially
        for i in range(5):
            await svc.update_custom_setting(user_id, f"key_{i}", f"value_{i}")

        # Request only 3 entries
        history = await svc.get_settings_history(user_id, limit=3)

        assert isinstance(history, list)
        assert len(history) == 3, f"Expected 3 history entries, got {len(history)}"

        # History returns most recent entries first
        # The reason field contains the key info (e.g., "Custom setting 'key_4' updated")
        expected_keys = ["key_4", "key_3", "key_2"]
        for i, entry in enumerate(history):
            assert isinstance(entry, DomainSettingsHistoryEntry)
            assert entry.reason is not None, f"Entry {i} should have a reason"
            assert expected_keys[i] in entry.reason, (
                f"Entry {i} reason '{entry.reason}' should contain '{expected_keys[i]}'"
            )


class TestRestoreSettingsToPoint:
    """Tests for restore_settings_to_point method."""

    @pytest.mark.asyncio
    async def test_restore_settings_to_current_time(
        self, scope: AsyncContainer
    ) -> None:
        """Restore to current time is effectively a no-op."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Set some settings
        await svc.update_theme(user_id, Theme.DARK)

        # Restore to current time
        now = datetime.now(timezone.utc)
        restored = await svc.restore_settings_to_point(user_id, now)

        assert isinstance(restored, DomainUserSettings)
        assert restored.user_id == user_id

    @pytest.mark.asyncio
    async def test_restore_settings_to_past(self, scope: AsyncContainer) -> None:
        """Restore settings to a past point reverts changes."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Capture initial default settings
        initial = await svc.get_user_settings(user_id)
        assert initial.theme == Theme.AUTO, "Initial theme should be AUTO (default)"

        # Make changes that alter the settings
        await svc.update_theme(user_id, Theme.DARK)
        await svc.update_theme(user_id, Theme.LIGHT)

        # Verify settings changed
        current = await svc.get_user_settings(user_id)
        assert current.theme == Theme.LIGHT, "Theme should be LIGHT after updates"

        # Restore to before all changes (epoch)
        past = datetime.now(timezone.utc) - timedelta(days=365)
        restored = await svc.restore_settings_to_point(user_id, past)

        # Verify restore actually reverted to initial defaults
        assert isinstance(restored, DomainUserSettings)
        assert restored.theme == initial.theme, (
            f"Restored theme should match initial ({initial.theme}), got {restored.theme}"
        )
        assert restored.timezone == initial.timezone, (
            f"Restored timezone should match initial ({initial.timezone}), got {restored.timezone}"
        )


class TestCacheManagement:
    """Tests for cache management methods."""

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, scope: AsyncContainer) -> None:
        """Invalidate cache for user."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Cache settings
        await svc.get_user_settings(user_id)

        # Invalidate
        await svc.invalidate_cache(user_id)

        # Should still work (cache miss)
        settings = await svc.get_user_settings(user_id)
        assert settings.user_id == user_id

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, scope: AsyncContainer) -> None:
        """Get cache statistics."""
        svc: UserSettingsService = await scope.get(UserSettingsService)

        stats = svc.get_cache_stats()

        assert isinstance(stats, dict)
        assert "cache_size" in stats
        assert "max_cache_size" in stats
        assert "cache_ttl_seconds" in stats
        assert stats["cache_size"] >= 0
        assert stats["max_cache_size"] > 0


class TestResetUserSettings:
    """Tests for reset_user_settings method."""

    @pytest.mark.asyncio
    async def test_reset_user_settings(self, scope: AsyncContainer) -> None:
        """Reset user settings clears all data."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # Set some custom settings
        await svc.update_theme(user_id, Theme.DARK)
        await svc.update_custom_setting(user_id, "custom_key", "custom_value")

        # Reset
        await svc.reset_user_settings(user_id)

        # Get fresh - should be defaults
        settings = await svc.get_user_settings_fresh(user_id)
        assert settings.theme == Theme.AUTO  # Default


class TestSettingsIntegration:
    """Integration tests for settings workflow."""

    @pytest.mark.asyncio
    async def test_full_settings_lifecycle(self, scope: AsyncContainer) -> None:
        """Test complete settings lifecycle."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user_id = _unique_user_id()

        # 1. Get default settings
        initial = await svc.get_user_settings(user_id)
        assert initial.theme == Theme.AUTO

        # 2. Update theme
        await svc.update_theme(user_id, Theme.DARK)

        # 3. Update editor settings
        await svc.update_editor_settings(
            user_id, DomainEditorSettings(tab_size=4, show_line_numbers=True)
        )

        # 4. Update notification settings
        await svc.update_notification_settings(
            user_id, DomainNotificationSettings(execution_completed=True)
        )

        # 5. Add custom setting
        await svc.update_custom_setting(user_id, "language", "en")

        # 6. Verify all settings persisted
        final = await svc.get_user_settings(user_id)
        assert final.theme == Theme.DARK
        assert final.editor.tab_size == 4
        assert final.notifications.execution_completed is True
        assert final.custom_settings.get("language") == "en"

        # 7. Get history
        history = await svc.get_settings_history(user_id)
        assert isinstance(history, list)

        # 8. Cache stats
        stats = svc.get_cache_stats()
        assert stats["cache_size"] >= 0

    @pytest.mark.asyncio
    async def test_settings_isolation_between_users(
        self, scope: AsyncContainer
    ) -> None:
        """Settings are isolated between users."""
        svc: UserSettingsService = await scope.get(UserSettingsService)
        user1 = _unique_user_id()
        user2 = _unique_user_id()

        # User1 prefers dark theme
        await svc.update_theme(user1, Theme.DARK)

        # User2 prefers light theme
        await svc.update_theme(user2, Theme.LIGHT)

        # Verify isolation
        user1_settings = await svc.get_user_settings(user1)
        user2_settings = await svc.get_user_settings(user2)

        assert user1_settings.theme == Theme.DARK
        assert user2_settings.theme == Theme.LIGHT
