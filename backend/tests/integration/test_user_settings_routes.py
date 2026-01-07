from datetime import datetime, timezone

import pytest
from app.domain.enums.user import UserRole
from app.schemas_pydantic.user_settings import SettingsHistoryResponse, UserSettings
from httpx import AsyncClient

from tests.conftest import MakeUser

# Force these tests to run sequentially on a single worker to avoid state conflicts
pytestmark = pytest.mark.xdist_group(name="user_settings")


@pytest.mark.integration
class TestUserSettingsRoutes:
    """Test user settings endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_user_settings_require_authentication(self, client: AsyncClient) -> None:
        """Test that user settings endpoints require authentication."""
        # Try to access settings without auth
        response = await client.get("/api/v1/user/settings/")
        assert response.status_code == 401

        error_data = response.json()
        assert "detail" in error_data
        assert any(word in error_data["detail"].lower()
                   for word in ["not authenticated", "unauthorized", "login"])

    @pytest.mark.asyncio
    async def test_get_user_settings(self, authenticated_client: AsyncClient) -> None:
        """Test getting user settings."""
        response = await authenticated_client.get("/api/v1/user/settings/")
        assert response.status_code == 200

        # Pydantic validates types and required fields
        settings = UserSettings(**response.json())

        # Verify business logic constraints (not type checks)
        assert settings.theme in ["light", "dark", "auto", "system"]
        assert 8 <= settings.editor.font_size <= 32
        assert settings.editor.tab_size in [2, 4, 8]

    @pytest.mark.asyncio
    async def test_update_user_settings(self, authenticated_client: AsyncClient) -> None:
        """Test updating user settings."""
        # Get current settings to preserve original values
        original_response = await authenticated_client.get("/api/v1/user/settings/")
        assert original_response.status_code == 200
        original_settings = original_response.json()

        # Update settings
        notifications = {
            "execution_completed": False,
            "execution_failed": True,
            "system_updates": True,
            "security_alerts": True,
            "channels": ["in_app", "webhook"],
        }
        editor = {
            "theme": "monokai",
            "font_size": 14,
            "tab_size": 4,
            "use_tabs": False,
            "word_wrap": True,
            "show_line_numbers": True,
        }
        update_data = {
            "theme": "dark" if original_settings["theme"] == "light" else "light",
            "timezone": "America/New_York" if original_settings["timezone"] != "America/New_York" else "UTC",
            "date_format": "MM/DD/YYYY",
            "time_format": "12h",
            "notifications": notifications,
            "editor": editor,
        }

        response = await authenticated_client.put("/api/v1/user/settings/", json=update_data)
        if response.status_code != 200:
            pytest.fail(f"Status: {response.status_code}, Body: {response.json()}, Data: {update_data}")
        assert response.status_code == 200

        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        assert updated_settings.theme == update_data["theme"]
        assert updated_settings.timezone == update_data["timezone"]
        assert updated_settings.date_format == update_data["date_format"]
        assert updated_settings.time_format == update_data["time_format"]

        # Verify notification settings were updated
        assert updated_settings.notifications.execution_completed == notifications["execution_completed"]
        assert updated_settings.notifications.execution_failed == notifications["execution_failed"]
        assert updated_settings.notifications.system_updates == notifications["system_updates"]
        assert updated_settings.notifications.security_alerts == notifications["security_alerts"]
        assert "in_app" in [str(c) for c in updated_settings.notifications.channels]

        # Verify editor settings were updated
        assert updated_settings.editor.theme == editor["theme"]
        assert updated_settings.editor.font_size == editor["font_size"]
        assert updated_settings.editor.tab_size == editor["tab_size"]
        assert updated_settings.editor.word_wrap == editor["word_wrap"]
        assert updated_settings.editor.show_line_numbers == editor["show_line_numbers"]

    @pytest.mark.asyncio
    async def test_update_theme_only(self, authenticated_client: AsyncClient) -> None:
        """Test updating only the theme setting."""
        # Get current theme
        original_response = await authenticated_client.get("/api/v1/user/settings/")
        assert original_response.status_code == 200
        original_theme = original_response.json()["theme"]

        # Update theme
        new_theme = "dark" if original_theme != "dark" else "light"
        theme_update = {
            "theme": new_theme
        }

        response = await authenticated_client.put("/api/v1/user/settings/theme", json=theme_update)
        assert response.status_code == 200

        # Validate updated settings
        updated_payload = response.json()
        updated_settings = UserSettings(**updated_payload)
        assert updated_settings.theme == new_theme

        # Other settings should remain unchanged (language optional)
        if "language" in original_response.json():
            assert updated_payload.get("language") == original_response.json()["language"]
        assert updated_settings.timezone == original_response.json()["timezone"]

    @pytest.mark.asyncio
    async def test_update_notification_settings_only(self, authenticated_client: AsyncClient) -> None:
        """Test updating only notification settings."""
        # Update notification settings
        notification_update = {
            "execution_completed": True,
            "execution_failed": True,
            "system_updates": False,
            "security_alerts": True,
            "channels": ["in_app"]
        }

        response = await authenticated_client.put("/api/v1/user/settings/notifications", json=notification_update)
        assert response.status_code == 200

        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        assert updated_settings.notifications.execution_completed == notification_update["execution_completed"]
        assert updated_settings.notifications.execution_failed == notification_update["execution_failed"]
        assert updated_settings.notifications.system_updates == notification_update["system_updates"]
        assert updated_settings.notifications.security_alerts == notification_update["security_alerts"]
        assert "in_app" in [str(c) for c in updated_settings.notifications.channels]

    @pytest.mark.asyncio
    async def test_update_editor_settings_only(self, authenticated_client: AsyncClient) -> None:
        """Test updating only editor settings."""
        # Update editor settings
        editor_update = {
            "theme": "dracula",
            "font_size": 16,
            "tab_size": 2,
            "use_tabs": False,
            "word_wrap": False,
            "show_line_numbers": True
        }

        response = await authenticated_client.put("/api/v1/user/settings/editor", json=editor_update)
        assert response.status_code == 200

        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        assert updated_settings.editor.theme == editor_update["theme"]
        assert updated_settings.editor.font_size == editor_update["font_size"]
        assert updated_settings.editor.tab_size == editor_update["tab_size"]
        assert updated_settings.editor.word_wrap == editor_update["word_wrap"]
        assert updated_settings.editor.show_line_numbers == editor_update["show_line_numbers"]

    @pytest.mark.asyncio
    async def test_update_custom_setting(self, authenticated_client: AsyncClient) -> None:
        """Test updating a custom setting."""
        # Update custom settings via main settings endpoint
        custom_key = "custom_preference"
        custom_value = "custom_value_123"
        update_data = {
            "custom_settings": {
                custom_key: custom_value
            }
        }

        response = await authenticated_client.put("/api/v1/user/settings/", json=update_data)
        assert response.status_code == 200

        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        assert custom_key in updated_settings.custom_settings
        assert updated_settings.custom_settings[custom_key] == custom_value

    @pytest.mark.asyncio
    async def test_get_settings_history(self, authenticated_client: AsyncClient) -> None:
        """Test getting settings change history."""
        # Make some changes to build history (theme change)
        theme_update = {"theme": "dark"}
        response = await authenticated_client.put("/api/v1/user/settings/theme", json=theme_update)
        assert response.status_code == 200

        # Get history
        history_response = await authenticated_client.get("/api/v1/user/settings/history")
        assert history_response.status_code == 200

        # Validate history structure
        history = SettingsHistoryResponse(**history_response.json())
        assert isinstance(history.history, list)

        # If we have history entries, validate them
        for entry in history.history:
            assert entry.timestamp is not None

    @pytest.mark.asyncio
    async def test_restore_settings_to_previous_point(self, authenticated_client: AsyncClient) -> None:
        """Test restoring settings to a previous point in time."""
        # Get original settings
        original_resp = await authenticated_client.get("/api/v1/user/settings/")
        assert original_resp.status_code == 200
        original_theme = original_resp.json()["theme"]

        # Make a change
        new_theme = "dark" if original_theme != "dark" else "light"
        await authenticated_client.put("/api/v1/user/settings/theme", json={"theme": new_theme})

        # Get restore point (after the change)
        restore_point = datetime.now(timezone.utc).isoformat()

        # Make another change
        second_theme = "auto" if new_theme != "auto" else "system"
        await authenticated_client.put("/api/v1/user/settings/theme", json={"theme": second_theme})

        # Try to restore to the restore point
        restore_data = {"timestamp": restore_point}
        restore_resp = await authenticated_client.post("/api/v1/user/settings/restore", json=restore_data)
        assert restore_resp.status_code == 200

        # Verify we get valid settings back
        current_resp = await authenticated_client.get("/api/v1/user/settings/")
        assert current_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_theme_value(self, authenticated_client: AsyncClient) -> None:
        """Test that invalid theme values are rejected."""
        invalid_theme = {"theme": "invalid_theme"}
        response = await authenticated_client.put("/api/v1/user/settings/theme", json=invalid_theme)
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_invalid_editor_settings(self, authenticated_client: AsyncClient) -> None:
        """Test that invalid editor settings are rejected."""
        # Try to update with invalid editor settings
        invalid_editor = {
            "theme": "dracula",
            "font_size": 100,  # Invalid: out of range
            "tab_size": 3,  # Invalid: not 2, 4, or 8
            "use_tabs": False,
            "word_wrap": True,
            "show_line_numbers": True
        }

        response = await authenticated_client.put("/api/v1/user/settings/editor", json=invalid_editor)
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_settings_isolation_between_users(
        self, client: AsyncClient, make_user: MakeUser,
    ) -> None:
        """Test that settings are isolated between users."""
        user1 = await make_user(UserRole.USER)
        user2 = await make_user(UserRole.USER)

        # Login as first user
        await client.post(
            "/api/v1/auth/login",
            data={"username": user1["username"], "password": user1["password"]},
        )

        # Update first user's settings
        user1_update = {"theme": "dark", "timezone": "America/New_York"}
        response = await client.put("/api/v1/user/settings/", json=user1_update)
        assert response.status_code == 200

        # Log out and login as second user
        await client.post("/api/v1/auth/logout")
        await client.post(
            "/api/v1/auth/login",
            data={"username": user2["username"], "password": user2["password"]},
        )

        # Get second user's settings
        response = await client.get("/api/v1/user/settings/")
        assert response.status_code == 200
        user2_settings = response.json()

        # Verify second user's settings are not affected by first user's changes
        assert (
            user2_settings["theme"] != user1_update["theme"]
            or user2_settings["timezone"] != user1_update["timezone"]
        )

    @pytest.mark.asyncio
    async def test_settings_persistence(self, client: AsyncClient, make_user: MakeUser) -> None:
        """Test that settings persist across login sessions."""
        user = await make_user(UserRole.USER)

        # Update settings
        editor = {
            "theme": "github",
            "font_size": 18,
            "tab_size": 8,
            "use_tabs": True,
            "word_wrap": False,
            "show_line_numbers": False,
        }
        update_data = {"theme": "dark", "timezone": "Europe/London", "editor": editor}

        response = await client.put("/api/v1/user/settings/", json=update_data)
        assert response.status_code == 200

        # Log out
        await client.post("/api/v1/auth/logout")

        # Log back in as same user
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": user["username"], "password": user["password"]},
        )
        assert login_resp.status_code == 200

        # Get settings again
        response = await client.get("/api/v1/user/settings/")
        assert response.status_code == 200
        persisted_settings = UserSettings(**response.json())

        # Verify settings persisted
        assert persisted_settings.theme == update_data["theme"]
        assert persisted_settings.timezone == update_data["timezone"]
        assert persisted_settings.editor.theme == editor["theme"]
        assert persisted_settings.editor.font_size == editor["font_size"]
        assert persisted_settings.editor.tab_size == editor["tab_size"]
        assert persisted_settings.editor.word_wrap == editor["word_wrap"]
        assert persisted_settings.editor.show_line_numbers == editor["show_line_numbers"]
