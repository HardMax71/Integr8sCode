import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.enums import Theme
from app.domain.user import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsUpdate,
)
from app.services.user_settings_service import UserSettingsService

pytestmark = [pytest.mark.e2e]


def _unique_user_id() -> str:
    return f"settings_user_{uuid.uuid4().hex[:8]}"


class TestGetUserSettings:
    """Tests for get_user_settings method."""

    async def test_get_user_settings_new_user(self, user_settings_service: UserSettingsService) -> None:
        """Get settings for new user returns defaults."""
        user_id = _unique_user_id()

        settings = await user_settings_service.get_user_settings(user_id)

        assert isinstance(settings, DomainUserSettings)
        assert settings.user_id == user_id
        assert settings.theme == Theme.SYSTEM  # Default theme
        assert settings.editor is not None
        assert settings.notifications is not None

    async def test_get_user_settings_reads_the_latest_update(self, user_settings_service: UserSettingsService) -> None:
        """A read right after an update returns it, with no cache to go stale."""
        user_id = _unique_user_id()

        await user_settings_service.get_user_settings(user_id)
        await user_settings_service.update_theme(user_id, Theme.DARK)

        settings = await user_settings_service.get_user_settings(user_id)
        assert settings.user_id == user_id
        assert settings.theme == Theme.DARK


class TestUpdateUserSettings:
    """Tests for update_user_settings method."""

    async def test_update_theme(self, user_settings_service: UserSettingsService) -> None:
        """Update theme setting."""
        user_id = _unique_user_id()

        # Update theme
        updates = DomainUserSettingsUpdate(theme=Theme.DARK)
        updated = await user_settings_service.update_user_settings(user_id, updates)

        assert updated.theme == Theme.DARK

        # Verify persistence
        retrieved = await user_settings_service.get_user_settings(user_id)
        assert retrieved.theme == Theme.DARK

    async def test_update_multiple_settings(self, user_settings_service: UserSettingsService) -> None:
        """Update multiple settings at once."""
        user_id = _unique_user_id()

        updates = DomainUserSettingsUpdate(
            theme=Theme.LIGHT,
            timezone="Europe/London",
            date_format="DD/MM/YYYY",
        )
        updated = await user_settings_service.update_user_settings(user_id, updates)

        assert updated.theme == Theme.LIGHT
        assert updated.timezone == "Europe/London"
        assert updated.date_format == "DD/MM/YYYY"

    async def test_update_with_reason(self, user_settings_service: UserSettingsService) -> None:
        """Update settings with reason tracked."""
        user_id = _unique_user_id()

        reason_text = "User preference"
        updates = DomainUserSettingsUpdate(theme=Theme.DARK)
        await user_settings_service.update_user_settings(user_id, updates, reason=reason_text)

        # Verify reason was persisted in history
        history = await user_settings_service.get_settings_history(user_id)
        assert isinstance(history, list)
        assert len(history) > 0, "Expected at least one history entry after update"

        # Find entry with our reason
        reasons_found = [entry.reason for entry in history if entry.reason == reason_text]
        assert len(reasons_found) > 0, (
            f"Expected history to contain entry with reason '{reason_text}', "
            f"found reasons: {[e.reason for e in history]}"
        )

    async def test_update_increments_version(self, user_settings_service: UserSettingsService) -> None:
        """Each update increments settings version."""
        user_id = _unique_user_id()

        # Get initial
        initial = await user_settings_service.get_user_settings(user_id)
        initial_version = initial.version or 0

        # Update
        updates = DomainUserSettingsUpdate(theme=Theme.DARK)
        updated = await user_settings_service.update_user_settings(user_id, updates)

        assert updated.version is not None
        assert updated.version > initial_version

    async def test_update_empty_changes_no_op(self, user_settings_service: UserSettingsService) -> None:
        """Empty update is a no-op."""
        user_id = _unique_user_id()

        # Get initial
        initial = await user_settings_service.get_user_settings(user_id)

        # Empty update
        updates = DomainUserSettingsUpdate()
        result = await user_settings_service.update_user_settings(user_id, updates)

        # Should return same settings
        assert result.theme == initial.theme


class TestUpdateTheme:
    """Tests for update_theme convenience method."""

    async def test_update_theme_to_dark(self, user_settings_service: UserSettingsService) -> None:
        """Update theme to dark."""
        user_id = _unique_user_id()

        result = await user_settings_service.update_theme(user_id, Theme.DARK)

        assert result.theme == Theme.DARK

    async def test_update_theme_to_light(self, user_settings_service: UserSettingsService) -> None:
        """Update theme to light."""
        user_id = _unique_user_id()

        result = await user_settings_service.update_theme(user_id, Theme.LIGHT)

        assert result.theme == Theme.LIGHT

    async def test_update_theme_to_system(self, user_settings_service: UserSettingsService) -> None:
        """Update theme to system default."""
        user_id = _unique_user_id()

        # First set to dark
        await user_settings_service.update_theme(user_id, Theme.DARK)

        # Then back to auto
        result = await user_settings_service.update_theme(user_id, Theme.SYSTEM)

        assert result.theme == Theme.SYSTEM


class TestUpdateNotificationSettings:
    """Tests for update_notification_settings method."""

    async def test_update_notification_settings(self, user_settings_service: UserSettingsService) -> None:
        """Update notification settings."""
        user_id = _unique_user_id()

        notification_settings = DomainNotificationSettings(
            execution_completed=True,
            execution_failed=True,
            system_updates=False,
        )
        result = await user_settings_service.update_notification_settings(user_id, notification_settings)

        assert result.notifications is not None
        assert result.notifications.execution_completed is True
        assert result.notifications.execution_failed is True
        assert result.notifications.system_updates is False

    async def test_disable_all_notifications(self, user_settings_service: UserSettingsService) -> None:
        """Disable all notifications."""
        user_id = _unique_user_id()

        notification_settings = DomainNotificationSettings(
            execution_completed=False,
            execution_failed=False,
            system_updates=False,
            security_alerts=False,
        )
        result = await user_settings_service.update_notification_settings(user_id, notification_settings)

        assert result.notifications.execution_completed is False


class TestUpdateEditorSettings:
    """Tests for update_editor_settings method."""

    async def test_update_editor_tab_size(self, user_settings_service: UserSettingsService) -> None:
        """Update editor tab size."""
        user_id = _unique_user_id()

        editor_settings = DomainEditorSettings(tab_size=4)
        result = await user_settings_service.update_editor_settings(user_id, editor_settings)

        assert result.editor is not None
        assert result.editor.tab_size == 4

    async def test_update_editor_multiple_options(self, user_settings_service: UserSettingsService) -> None:
        """Update multiple editor settings."""
        user_id = _unique_user_id()

        editor_settings = DomainEditorSettings(
            tab_size=2,
            show_line_numbers=True,
            word_wrap=True,
            font_size=14,
        )
        result = await user_settings_service.update_editor_settings(user_id, editor_settings)

        assert result.editor.tab_size == 2
        assert result.editor.show_line_numbers is True
        assert result.editor.word_wrap is True
        assert result.editor.font_size == 14


class TestUpdateCustomSetting:
    """Tests for update_custom_setting method."""

    async def test_update_custom_setting_string(self, user_settings_service: UserSettingsService) -> None:
        """Update custom setting with string value."""
        user_id = _unique_user_id()

        result = await user_settings_service.update_custom_setting(user_id, "favorite_color", "blue")

        assert result.custom_settings is not None
        assert result.custom_settings.get("favorite_color") == "blue"

    async def test_update_custom_setting_number(self, user_settings_service: UserSettingsService) -> None:
        """Update custom setting with number value."""
        user_id = _unique_user_id()

        result = await user_settings_service.update_custom_setting(user_id, "max_results", 100)

        assert result.custom_settings.get("max_results") == 100

    async def test_update_custom_setting_boolean(self, user_settings_service: UserSettingsService) -> None:
        """Update custom setting with boolean value."""
        user_id = _unique_user_id()

        result = await user_settings_service.update_custom_setting(user_id, "beta_features", True)

        assert result.custom_settings.get("beta_features") is True

    async def test_update_multiple_custom_settings(self, user_settings_service: UserSettingsService) -> None:
        """Update multiple custom settings sequentially."""
        user_id = _unique_user_id()

        await user_settings_service.update_custom_setting(user_id, "key1", "value1")
        await user_settings_service.update_custom_setting(user_id, "key2", "value2")
        result = await user_settings_service.update_custom_setting(user_id, "key3", "value3")

        assert result.custom_settings.get("key1") == "value1"
        assert result.custom_settings.get("key2") == "value2"
        assert result.custom_settings.get("key3") == "value3"


class TestGetSettingsHistory:
    """Tests for get_settings_history method."""

    async def test_get_settings_history_empty(self, user_settings_service: UserSettingsService) -> None:
        """New user has no history."""
        user_id = _unique_user_id()

        history = await user_settings_service.get_settings_history(user_id)

        assert isinstance(history, list)

    async def test_get_settings_history_after_updates(self, user_settings_service: UserSettingsService) -> None:
        """History contains entries after updates."""
        user_id = _unique_user_id()

        # Make some updates
        await user_settings_service.update_theme(user_id, Theme.DARK)
        await user_settings_service.update_theme(user_id, Theme.LIGHT)

        history = await user_settings_service.get_settings_history(user_id)

        assert isinstance(history, list)
        # Should have at least some history entries
        for entry in history:
            assert isinstance(entry, DomainSettingsHistoryEntry)
            assert entry.timestamp is not None

    async def test_get_settings_history_with_limit(self, user_settings_service: UserSettingsService) -> None:
        """History respects limit parameter and returns most recent entries."""
        user_id = _unique_user_id()

        # Make 5 updates sequentially
        for i in range(5):
            await user_settings_service.update_custom_setting(user_id, f"key_{i}", f"value_{i}")

        # Request only 3 entries
        history = await user_settings_service.get_settings_history(user_id, limit=3)

        assert isinstance(history, list)
        assert len(history) == 3, f"Expected 3 history entries, got {len(history)}"

        # History returns the newest entries first
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

    async def test_restore_settings_to_current_time(self, user_settings_service: UserSettingsService) -> None:
        """Restore to current time is effectively a no-op."""
        user_id = _unique_user_id()

        # Set some settings
        await user_settings_service.update_theme(user_id, Theme.DARK)

        # Restore to current time
        now = datetime.now(timezone.utc)
        restored = await user_settings_service.restore_settings_to_point(user_id, now)

        assert isinstance(restored, DomainUserSettings)
        assert restored.user_id == user_id

    async def test_restore_settings_to_past(self, user_settings_service: UserSettingsService) -> None:
        """Restore settings to a past point reverts changes."""
        user_id = _unique_user_id()

        # Capture initial default settings
        initial = await user_settings_service.get_user_settings(user_id)
        assert initial.theme == Theme.SYSTEM, "Initial theme should be SYSTEM (default)"

        # Make changes that alter the settings
        await user_settings_service.update_theme(user_id, Theme.DARK)
        await user_settings_service.update_theme(user_id, Theme.LIGHT)

        # Verify settings changed
        current = await user_settings_service.get_user_settings(user_id)
        assert current.theme == Theme.LIGHT, "Theme should be LIGHT after updates"

        # Restore to before all changes (epoch)
        past = datetime.now(timezone.utc) - timedelta(days=365)
        restored = await user_settings_service.restore_settings_to_point(user_id, past)

        # Verify restore actually reverted to initial defaults
        assert isinstance(restored, DomainUserSettings)
        assert restored.theme == initial.theme, (
            f"Restored theme should match initial ({initial.theme}), got {restored.theme}"
        )
        assert restored.timezone == initial.timezone, (
            f"Restored timezone should match initial ({initial.timezone}), got {restored.timezone}"
        )
        rebuilt = await user_settings_service.get_user_settings(user_id)
        assert rebuilt.theme == initial.theme


class TestSettingsIntegration:
    """Integration tests for settings workflow."""

    async def test_full_settings_lifecycle(self, user_settings_service: UserSettingsService) -> None:
        """Test complete settings lifecycle."""
        user_id = _unique_user_id()

        # 1. Get default settings
        initial = await user_settings_service.get_user_settings(user_id)
        assert initial.theme == Theme.SYSTEM

        # 2. Update theme
        await user_settings_service.update_theme(user_id, Theme.DARK)

        # 3. Update editor settings
        await user_settings_service.update_editor_settings(
            user_id, DomainEditorSettings(tab_size=4, show_line_numbers=True)
        )

        # 4. Update notification settings
        await user_settings_service.update_notification_settings(
            user_id, DomainNotificationSettings(execution_completed=True)
        )

        # 5. Add custom setting
        await user_settings_service.update_custom_setting(user_id, "language", "en")

        # 6. Verify all settings persisted
        final = await user_settings_service.get_user_settings(user_id)
        assert final.theme == Theme.DARK
        assert final.editor.tab_size == 4
        assert final.notifications.execution_completed is True
        assert final.custom_settings.get("language") == "en"

        # 7. Get history
        history = await user_settings_service.get_settings_history(user_id)
        assert isinstance(history, list)

    async def test_settings_isolation_between_users(self, user_settings_service: UserSettingsService) -> None:
        """Settings are isolated between users."""
        user1 = _unique_user_id()
        user2 = _unique_user_id()

        # User1 prefers dark theme
        await user_settings_service.update_theme(user1, Theme.DARK)

        # User2 prefers light theme
        await user_settings_service.update_theme(user2, Theme.LIGHT)

        # Verify isolation
        user1_settings = await user_settings_service.get_user_settings(user1)
        user2_settings = await user_settings_service.get_user_settings(user2)

        assert user1_settings.theme == Theme.DARK
        assert user2_settings.theme == Theme.LIGHT
