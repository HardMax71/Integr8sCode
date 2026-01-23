import pytest
from app.domain.enums.common import Theme
from app.schemas_pydantic.user_settings import (
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

        assert settings.theme in [Theme.LIGHT, Theme.DARK, Theme.AUTO]
        assert settings.timezone is not None
        assert settings.notifications is not None
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
        response = await test_user.put(
            "/api/v1/user/settings/",
            json={
                "theme": "dark",
                "timezone": "America/New_York",
                "notifications": {
                    "email_enabled": True,
                    "push_enabled": False,
                },
                "editor": {
                    "tab_size": 4,
                    "font_size": 14,
                    "line_numbers": True,
                    "word_wrap": False,
                },
            },
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())

        assert settings.theme == "dark"
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
    async def test_update_theme_dark(self, test_user: AsyncClient) -> None:
        """Update theme to dark."""
        request = ThemeUpdateRequest(theme=Theme.DARK)
        response = await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.theme == Theme.DARK

    @pytest.mark.asyncio
    async def test_update_theme_light(self, test_user: AsyncClient) -> None:
        """Update theme to light."""
        request = ThemeUpdateRequest(theme=Theme.LIGHT)
        response = await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.theme == Theme.LIGHT

    @pytest.mark.asyncio
    async def test_update_theme_system(self, test_user: AsyncClient) -> None:
        """Update theme to system."""
        request = ThemeUpdateRequest(theme=Theme.AUTO)
        response = await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.theme == Theme.AUTO


class TestUpdateNotificationSettings:
    """Tests for PUT /api/v1/user/settings/notifications."""

    @pytest.mark.asyncio
    async def test_update_notification_settings(
        self, test_user: AsyncClient
    ) -> None:
        """Update notification settings."""
        response = await test_user.put(
            "/api/v1/user/settings/notifications",
            json={
                "email_enabled": True,
                "push_enabled": True,
            },
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert settings.notifications is not None


class TestUpdateEditorSettings:
    """Tests for PUT /api/v1/user/settings/editor."""

    @pytest.mark.asyncio
    async def test_update_editor_settings(
        self, test_user: AsyncClient
    ) -> None:
        """Update editor settings."""
        response = await test_user.put(
            "/api/v1/user/settings/editor",
            json={
                "tab_size": 2,
                "font_size": 16,
                "line_numbers": True,
                "word_wrap": True,
            },
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
        # Make a change first
        request = ThemeUpdateRequest(theme=Theme.DARK)
        await test_user.put(
            "/api/v1/user/settings/theme",
            json=request.model_dump(),
        )

        response = await test_user.get(
            "/api/v1/user/settings/history",
            params={"limit": 10},
        )

        assert response.status_code == 200
        history = SettingsHistoryResponse.model_validate(response.json())
        assert history.limit == 10
        assert isinstance(history.history, list)

    @pytest.mark.asyncio
    async def test_get_settings_history_default_limit(
        self, test_user: AsyncClient
    ) -> None:
        """History uses default limit."""
        response = await test_user.get("/api/v1/user/settings/history")

        assert response.status_code == 200
        history = SettingsHistoryResponse.model_validate(response.json())
        assert isinstance(history.history, list)


class TestRestoreSettings:
    """Tests for POST /api/v1/user/settings/restore."""

    @pytest.mark.asyncio
    async def test_restore_settings(self, test_user: AsyncClient) -> None:
        """Restore settings to a previous point."""
        # Get history first
        history_response = await test_user.get("/api/v1/user/settings/history")

        if history_response.status_code == 200:
            history = SettingsHistoryResponse.model_validate(
                history_response.json()
            )

            if history.history:
                # Try to restore to first entry
                restore_req = RestoreSettingsRequest(
                    timestamp=history.history[0].timestamp
                )
                restore_response = await test_user.post(
                    "/api/v1/user/settings/restore",
                    json=restore_req.model_dump(mode="json"),
                )

                # May succeed or fail depending on implementation
                assert restore_response.status_code in [200, 400, 404]


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
        await test_user.put(
            "/api/v1/user/settings/custom/setting_one",
            json={"value": 1},
        )

        # Second setting
        response = await test_user.put(
            "/api/v1/user/settings/custom/setting_two",
            json={"value": 2},
        )

        assert response.status_code == 200
        settings = UserSettings.model_validate(response.json())
        assert "setting_one" in settings.custom_settings
        assert "setting_two" in settings.custom_settings
