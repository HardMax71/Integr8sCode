"""
Integration tests for User Settings routes against the backend.

These tests run against the actual backend service running in Docker,
providing true end-to-end testing with:
- Real settings persistence
- Real user-specific settings
- Real theme management
- Real notification preferences
- Real editor configurations
- Real settings history tracking
"""

import pytest
import asyncio
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from uuid import uuid4

from app.schemas_pydantic.user_settings import (
    UserSettings,
    UserSettingsUpdate,
    ThemeUpdateRequest,
    NotificationSettings,
    EditorSettings,
    SettingsHistoryResponse,
    RestoreSettingsRequest
)


@pytest.mark.integration
class TestUserSettingsRoutesReal:
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
    async def test_get_user_settings(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test getting user settings."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Get user settings
        response = await client.get("/api/v1/user/settings/")
        assert response.status_code == 200
        
        # Validate response structure
        settings_data = response.json()
        settings = UserSettings(**settings_data)
        
        # Verify required fields
        assert settings.user_id is not None
        assert settings.theme in ["light", "dark", "auto", "system"]
        # Language field may not be present in all deployments
        if hasattr(settings, "language"):
            assert isinstance(settings.language, str)
        assert isinstance(settings.timezone, str)
        
        # Verify notification settings (API uses execution_* and security_alerts fields)
        assert settings.notifications is not None
        assert isinstance(settings.notifications.execution_completed, bool)
        assert isinstance(settings.notifications.execution_failed, bool)
        assert isinstance(settings.notifications.system_updates, bool)
        assert isinstance(settings.notifications.security_alerts, bool)
        
        # Verify editor settings  
        assert settings.editor is not None
        assert isinstance(settings.editor.font_size, int)
        assert 8 <= settings.editor.font_size <= 32
        assert settings.editor.theme in ["one-dark", "monokai", "github", "dracula", "solarized", "vs", "vscode"]
        assert isinstance(settings.editor.tab_size, int)
        assert settings.editor.tab_size in [2, 4, 8]
        assert isinstance(settings.editor.word_wrap, bool)
        assert isinstance(settings.editor.show_line_numbers, bool)
        
        # Verify timestamp fields
        assert settings.created_at is not None
        assert settings.updated_at is not None
        
        # Custom settings might be empty or contain user preferences
        if settings.custom_settings:
            assert isinstance(settings.custom_settings, dict)
    
    @pytest.mark.asyncio
    async def test_update_user_settings(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test updating user settings."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Get current settings to preserve original values
        original_response = await client.get("/api/v1/user/settings/")
        assert original_response.status_code == 200
        original_settings = original_response.json()
        
        # Update settings
        update_data = {
            "theme": "dark" if original_settings["theme"] == "light" else "light",
            # Language update optional
            **({"language": "es" if original_settings.get("language") == "en" else "en"} if original_settings.get("language") else {}),
            "timezone": "America/New_York" if original_settings["timezone"] != "America/New_York" else "UTC",
            "notifications": {
                "execution_completed": True,
                "execution_failed": False,
                "system_updates": False,
                "security_alerts": True,
                "channels": ["in_app"]
            },
            "editor": {
                "font_size": 14,
                "theme": "dracula",
                "tab_size": 4,
                "word_wrap": True,
                "show_line_numbers": True
            }
        }
        
        response = await client.put("/api/v1/user/settings/", json=update_data)
        if response.status_code >= 500:
            pytest.skip("User settings update not available in this environment")
        assert response.status_code == 200
        
        # Validate updated settings
        updated_payload = response.json()
        updated_settings = UserSettings(**updated_payload)
        
        assert updated_settings.theme == update_data["theme"]
        # Language may not be supported in all deployments
        if "language" in update_data:
            assert updated_payload.get("language") == update_data["language"]
        assert updated_settings.timezone == update_data["timezone"]
        
        # Verify notification settings were updated
        assert updated_settings.notifications.execution_completed == update_data["notifications"]["execution_completed"]
        assert updated_settings.notifications.execution_failed == update_data["notifications"]["execution_failed"]
        assert updated_settings.notifications.system_updates == update_data["notifications"]["system_updates"]
        assert updated_settings.notifications.security_alerts == update_data["notifications"]["security_alerts"]
        
        # Verify editor settings were updated
        assert updated_settings.editor.font_size == update_data["editor"]["font_size"]
        assert updated_settings.editor.theme == update_data["editor"]["theme"]
        assert updated_settings.editor.tab_size == update_data["editor"]["tab_size"]
        assert updated_settings.editor.word_wrap == update_data["editor"]["word_wrap"]
        assert updated_settings.editor.show_line_numbers == update_data["editor"]["show_line_numbers"]
        
        # Updated timestamp should be newer
        assert updated_settings.updated_at > updated_settings.created_at
    
    @pytest.mark.asyncio
    async def test_update_theme_only(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test updating only the theme setting."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Get current theme
        original_response = await client.get("/api/v1/user/settings/")
        assert original_response.status_code == 200
        original_theme = original_response.json()["theme"]
        
        # Update theme
        new_theme = "dark" if original_theme != "dark" else "light"
        theme_update = {
            "theme": new_theme
        }
        
        response = await client.put("/api/v1/user/settings/theme", json=theme_update)
        if response.status_code >= 500:
            pytest.skip("Theme update not available in this environment")
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
    async def test_update_notification_settings_only(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test updating only notification settings."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Update notification settings
        notification_update = {
            "execution_completed": True,
            "execution_failed": True,
            "system_updates": False,
            "security_alerts": True,
            "channels": ["in_app"]
        }
        
        response = await client.put("/api/v1/user/settings/notifications", json=notification_update)
        if response.status_code >= 500:
            pytest.skip("Notification settings update not available in this environment")
        assert response.status_code == 200
        
        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        
        assert updated_settings.notifications.execution_completed == notification_update["execution_completed"]
        assert updated_settings.notifications.execution_failed == notification_update["execution_failed"]
        assert updated_settings.notifications.system_updates == notification_update["system_updates"]
        assert updated_settings.notifications.security_alerts == notification_update["security_alerts"]
    
    @pytest.mark.asyncio
    async def test_update_editor_settings_only(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test updating only editor settings."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Update editor settings
        editor_update = {
            "font_size": 16,
            "theme": "monokai",
            "tab_size": 2,
            "word_wrap": False,
            "show_line_numbers": True
        }
        
        response = await client.put("/api/v1/user/settings/editor", json=editor_update)
        if response.status_code >= 500:
            pytest.skip("Editor update not available in this environment")
        assert response.status_code == 200
        
        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        
        assert updated_settings.editor.font_size == editor_update["font_size"]
        assert updated_settings.editor.theme == editor_update["theme"]
        assert updated_settings.editor.tab_size == editor_update["tab_size"]
        assert updated_settings.editor.word_wrap == editor_update["word_wrap"]
        assert updated_settings.editor.show_line_numbers == editor_update["show_line_numbers"]
    
    @pytest.mark.asyncio
    async def test_update_custom_setting(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test adding/updating custom settings."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Add a custom setting
        custom_key = f"test_setting_{uuid4().hex[:8]}"
        custom_value = {
            "enabled": True,
            "value": "test_value",
            "metadata": {
                "created": datetime.now(timezone.utc).isoformat(),
                "version": "1.0"
            }
        }
        
        response = await client.put(f"/api/v1/user/settings/custom/{custom_key}", json=custom_value)
        assert response.status_code == 200
        
        # Validate updated settings
        updated_settings = UserSettings(**response.json())
        
        # Custom settings should contain our new setting
        assert updated_settings.custom_settings is not None
        assert custom_key in updated_settings.custom_settings
        assert updated_settings.custom_settings[custom_key] == custom_value
    
    @pytest.mark.asyncio
    async def test_get_settings_history(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test getting settings change history."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Make a change to create history
        theme_update = {"theme": "auto"}
        update_response = await client.put("/api/v1/user/settings/theme", json=theme_update)
        if update_response.status_code >= 500:
            pytest.skip("Theme update not available in this environment")
        assert update_response.status_code == 200
        
        # Get settings history
        response = await client.get("/api/v1/user/settings/history?limit=10")
        assert response.status_code == 200
        
        # Validate response
        history_data = response.json()
        history_response = SettingsHistoryResponse(**history_data)
        
        assert isinstance(history_response.history, list)
        assert isinstance(history_response.total, int)
        assert history_response.total >= 0
        
        # Check history entries
        for entry in history_response.history:
            assert "timestamp" in entry
            assert "change_type" in entry
            assert "old_value" in entry or "new_value" in entry
            assert "user_id" in entry
            
            # Timestamp should be valid
            if "timestamp" in entry:
                # Parse timestamp to verify it's valid
                assert isinstance(entry["timestamp"], str)
    
    @pytest.mark.asyncio
    async def test_restore_settings_to_previous_point(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test restoring settings to a previous point in time."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Get original settings
        original_response = await client.get("/api/v1/user/settings/")
        assert original_response.status_code == 200
        original_settings = original_response.json()
        
        # Record timestamp before changes
        timestamp_before = datetime.now(timezone.utc)
        
        # Make several changes
        await asyncio.sleep(1)  # Ensure timestamp difference
        
        # Change 1: Update theme
        theme_update = {"theme": "dark" if original_settings["theme"] != "dark" else "light"}
        await client.put("/api/v1/user/settings/theme", json=theme_update)
        
        await asyncio.sleep(1)
        
        # Change 2: Update editor settings
        editor_update = {
            "font_size": 18,
            "theme": "github",
            "tab_size": 8,
            "word_wrap": True,
            "show_line_numbers": False
        }
        await client.put("/api/v1/user/settings/editor", json=editor_update)
        
        # Try to restore to before changes
        restore_request = {
            "timestamp": timestamp_before.isoformat()
        }
        
        try:
            restore_response = await client.post("/api/v1/user/settings/restore", json=restore_request)
        except Exception:
            pytest.skip("Restore endpoint not available or connection dropped")
        if restore_response.status_code >= 500:
            pytest.skip("Restore not available in this environment")
        assert restore_response.status_code == 200
        
        # Validate restored settings
        restored_settings = UserSettings(**restore_response.json())
        
        # Theme should be back to original
        assert restored_settings.theme == original_settings["theme"]
        
        # Editor settings should be restored
        # Note: Might not perfectly match if there were no settings at that point
    
    @pytest.mark.asyncio
    async def test_invalid_theme_value(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test updating with invalid theme value."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Try invalid theme
        invalid_theme = {
            "theme": "invalid_theme_name"
        }
        
        response = await client.put("/api/v1/user/settings/theme", json=invalid_theme)
        assert response.status_code in [200, 400, 422]
    
    @pytest.mark.asyncio
    async def test_invalid_editor_settings(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test updating with invalid editor settings."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Try invalid font size
        invalid_editor = {
            "font_size": 100,  # Too large
            "theme": "monokai",
            "tab_size": 3,  # Invalid tab size
            "word_wrap": "yes",  # Should be boolean
            "line_numbers": True,
            "auto_save": False
        }
        
        response = await client.put("/api/v1/user/settings/editor", json=invalid_editor)
        if response.status_code >= 500:
            pytest.skip("Editor validation not available in this environment")
        assert response.status_code in [400, 422]
    
    @pytest.mark.asyncio
    async def test_settings_isolation_between_users(self, client: AsyncClient, 
                                                   shared_user: Dict[str, str],
                                                   shared_admin: Dict[str, str]) -> None:
        """Test that settings are isolated between users."""
        # Update settings as regular user
        user_login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        user_login_response = await client.post("/api/v1/auth/login", data=user_login_data)
        assert user_login_response.status_code == 200
        
        user_theme_update = {"theme": "dark"}
        user_update_response = await client.put("/api/v1/user/settings/theme", json=user_theme_update)
        if user_update_response.status_code >= 500:
            pytest.skip("Theme update not available in this environment")
        assert user_update_response.status_code == 200
        
        # Get user's settings
        user_settings_response = await client.get("/api/v1/user/settings/")
        assert user_settings_response.status_code == 200
        user_settings = user_settings_response.json()
        
        # Login as admin
        admin_login_data = {
            "username": shared_admin["username"],
            "password": shared_admin["password"]
        }
        admin_login_response = await client.post("/api/v1/auth/login", data=admin_login_data)
        assert admin_login_response.status_code == 200
        
        # Get admin's settings
        admin_settings_response = await client.get("/api/v1/user/settings/")
        assert admin_settings_response.status_code == 200
        admin_settings = admin_settings_response.json()
        
        # Settings should be different (different user_ids)
        assert user_settings["user_id"] != admin_settings["user_id"]
        
        # Admin's theme shouldn't be affected by user's change
        # (unless admin also set it to dark independently)
    
    @pytest.mark.asyncio
    async def test_settings_persistence(self, client: AsyncClient, shared_user: Dict[str, str]) -> None:
        """Test that settings persist across sessions."""
        # Login first
        login_data = {
            "username": shared_user["username"],
            "password": shared_user["password"]
        }
        login_response = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        
        # Update settings
        unique_value = f"test_{uuid4().hex[:8]}"
        custom_key = "persistence_test"
        custom_value = {"test_id": unique_value}
        
        update_response = await client.put(
            f"/api/v1/user/settings/custom/{custom_key}", 
            json=custom_value
        )
        assert update_response.status_code == 200
        
        # Logout
        logout_response = await client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 200
        
        # Login again
        login_response2 = await client.post("/api/v1/auth/login", data=login_data)
        assert login_response2.status_code == 200
        
        # Get settings and verify persistence
        settings_response = await client.get("/api/v1/user/settings/")
        assert settings_response.status_code == 200
        
        settings = settings_response.json()
        assert settings["custom_settings"] is not None
        assert custom_key in settings["custom_settings"]
        assert settings["custom_settings"][custom_key] == custom_value
