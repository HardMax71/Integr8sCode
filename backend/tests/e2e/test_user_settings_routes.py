import pytest
from app.domain.enums import Theme
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    RestoreSettingsRequest,
    SettingsHistoryResponse,
    ThemeUpdateRequest,
    UserSettings,
    UserSettingsUpdate,
)
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e]


class TestGetUserSettings:
    """Tests for GET /api/v1/user/settings/."""

    @pytest.mark.asyncio
    async def test_get_user_settings(self, test_user: AsyncClient) -> None:
        """Get current user settings."""
        response = await test_user.get("/api/v1/user/settings/")

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())

        assert settings.theme in list(Theme)
        assert settings.timezone
        assert settings.editor is not None

    @pytest.mark.asyncio
    async def test_get_user_settings_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/user/settings/")
        assert response.status_code == 401


class TestUpdateUserSettings:
    """Tests for PUT /api/v1/user/settings/."""

    @pytest.mark.asyncio
    async def test_update_user_settings_full(
        self, test_user: AsyncClient
    ) -> None:
        """Update all user settings."""
        request = UserSettingsUpdate(
            theme=Theme.DARK,
            timezone="America/New_York",
            notifications=NotificationSettings(
                execution_completed=True,
                execution_failed=True,
                system_updates=False,
                security_alerts=True,
            ),
            editor=EditorSettings(
                tab_size=4,
                font_size=14,
                show_line_numbers=True,
                word_wrap=False,
            ),
        )
        response = await test_user.put(
            "/api/v1/user/settings/",
            json=request.model_dump(exclude_unset=True),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())

        assert settings.theme == Theme.DARK
        assert settings.timezone == "America/New_York"

    @pytest.mark.asyncio
    async def test_update_user_settings_partial(
        self, test_user: AsyncClient
    ) -> None:
        """Update only some settings."""
        request = UserSettingsUpdate(theme=Theme.LIGHT)
        response = await test_user.put(
            "/api/v1/user/settings/",
            json=request.model_dump(exclude_unset=True),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.theme == Theme.LIGHT


class TestUpdateTheme:
    """Tests for PUT /api/v1/user/settings/theme."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("theme", list(Theme), ids=str)
    async def test_update_theme(
        self, test_user: AsyncClient, theme: Theme
    ) -> None:
        """Update theme to each valid value."""
        request = ThemeUpdateRequest(theme=theme)
        response = await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.theme == theme


class TestUpdateNotificationSettings:
    """Tests for PUT /api/v1/user/settings/notifications."""

    @pytest.mark.asyncio
    async def test_update_notification_settings(
        self, test_user: AsyncClient
    ) -> None:
        """Update notification settings."""
        request = NotificationSettings(
            execution_completed=True,
            execution_failed=True,
            system_updates=True,
            security_alerts=True,
        )
        response = await test_user.put(
            "/api/v1/user/settings/notifications",
            json=request.model_dump(),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.notifications.execution_completed is True
        assert settings.notifications.execution_failed is True
        assert settings.notifications.system_updates is True
        assert settings.notifications.security_alerts is True


class TestUpdateEditorSettings:
    """Tests for PUT /api/v1/user/settings/editor."""

    @pytest.mark.asyncio
    async def test_update_editor_settings(
        self, test_user: AsyncClient
    ) -> None:
        """Update editor settings."""
        request = EditorSettings(
            tab_size=2,
            font_size=16,
            show_line_numbers=True,
            word_wrap=True,
        )
        response = await test_user.put(
            "/api/v1/user/settings/editor",
            json=request.model_dump(),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.editor.tab_size == 2
        assert settings.editor.font_size == 16
        assert settings.editor.word_wrap is True

    @pytest.mark.asyncio
    async def test_update_editor_settings_partial(
        self, test_user: AsyncClient
    ) -> None:
        """Update only some editor settings."""
        response = await test_user.put(
            "/api/v1/user/settings/editor",
            json={"tab_size": 4},
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.editor.tab_size == 4


class TestSettingsHistory:
    """Tests for GET /api/v1/user/settings/history."""

    @pytest.mark.asyncio
    async def test_get_settings_history(self, test_user: AsyncClient) -> None:
        """Get settings change history."""
        # Make a change first to ensure history exists
        request = ThemeUpdateRequest(theme=Theme.DARK)
        update_response = await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )
        assert update_response.status_code == 200

        response = await test_user.get(
            "/api/v1/user/settings/history",
            params={"limit": 10},
        )

        assert response.status_code == 200
        history = SettingsHistoryResponse.model_validate(response.json())
        assert history.limit == 10
        assert len(history.history) >= 1

    @pytest.mark.asyncio
    async def test_get_settings_history_default_limit(
        self, test_user: AsyncClient
    ) -> None:
        """History uses default limit."""
        response = await test_user.get("/api/v1/user/settings/history")

        assert response.status_code == 200
        SettingsHistoryResponse.model_validate(response.json())


class TestRestoreSettings:
    """Tests for POST /api/v1/user/settings/restore."""

    @pytest.mark.asyncio
    async def test_restore_settings(self, test_user: AsyncClient) -> None:
        """Restore settings to a previous point."""
        # Make a change first to ensure history exists
        request = ThemeUpdateRequest(theme=Theme.DARK)
        update_response = await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )
        assert update_response.status_code == 200

        # Get history
        history_response = await test_user.get("/api/v1/user/settings/history")
        assert history_response.status_code == 200

        history = SettingsHistoryResponse.model_validate(history_response.json())
        assert len(history.history) >= 1, "No history entries found after settings update"

        # Restore to first entry
        restore_req = RestoreSettingsRequest(timestamp=history.history[0].timestamp)
        restore_response = await test_user.post(
            "/api/v1/user/settings/restore",
            json=restore_req.model_dump(mode="json"),
        )

        assert restore_response.status_code == 200
        restored = UserSettings.model_validate(restore_response.json())
        assert restored.theme in list(Theme)


class TestCustomSettings:
    """Tests for PUT /api/v1/user/settings/custom/{key}."""

    @pytest.mark.asyncio
    async def test_update_custom_setting(self, test_user: AsyncClient) -> None:
        """Update a custom setting."""
        response = await test_user.put(
            "/api/v1/user/settings/custom/my_preference",
            json={"value": "custom_value", "nested": {"key": 123}},
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert "my_preference" in settings.custom_settings

    @pytest.mark.asyncio
    async def test_update_multiple_custom_settings(
        self, test_user: AsyncClient
    ) -> None:
        """Update multiple custom settings."""
        # First setting
        first_response = await test_user.put(
            "/api/v1/user/settings/custom/setting_one",
            json={"value": 1},
        )
        assert first_response.status_code == 200
        first_settings = UserSettings.model_validate(first_response.json())
        assert "setting_one" in first_settings.custom_settings

        # Second setting
        second_response = await test_user.put(
            "/api/v1/user/settings/custom/setting_two",
            json={"value": 2},
        )
        assert second_response.status_code == 200
        second_settings = UserSettings.model_validate(second_response.json())
        assert "setting_one" in second_settings.custom_settings
        assert "setting_two" in second_settings.custom_settings
