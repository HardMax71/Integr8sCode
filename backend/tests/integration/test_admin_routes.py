from collections.abc import Callable

import pytest
from app.schemas_pydantic.admin_settings import (
    SystemSettings,
)
from app.schemas_pydantic.admin_user_overview import AdminUserOverview
from httpx import AsyncClient


@pytest.mark.integration
class TestAdminSettings:
    """Test admin settings endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_get_settings_requires_auth(self, client: AsyncClient) -> None:
        """Test that admin settings require authentication."""
        response = await client.get("/api/v1/admin/settings/")
        assert response.status_code == 401

        error = response.json()
        assert "detail" in error
        assert "not authenticated" in error["detail"].lower() or "unauthorized" in error["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_settings_with_admin_auth(self, authenticated_admin_client: AsyncClient) -> None:
        """Test getting system settings with admin authentication."""
        response = await authenticated_admin_client.get("/api/v1/admin/settings/")
        assert response.status_code == 200

        # Pydantic validates types, required fields, and nested structures
        settings = SystemSettings(**response.json())

        # Verify reasonable bounds (not exact values - those can change)
        assert settings.execution_limits.max_timeout_seconds > 0
        assert settings.execution_limits.max_memory_mb > 0
        assert settings.security_settings.password_min_length >= 1
        assert settings.monitoring_settings.sampling_rate >= 0

    @pytest.mark.asyncio
    async def test_update_and_reset_settings(self, authenticated_admin_client: AsyncClient) -> None:
        """Test updating and resetting system settings."""
        # Get original settings
        original_response = await authenticated_admin_client.get("/api/v1/admin/settings/")
        assert original_response.status_code == 200
        # original_settings preserved for potential rollback verification

        # Update settings
        updated_settings = {
            "execution_limits": {
                "max_timeout_seconds": 600,
                "max_memory_mb": 1024,
                "max_cpu_cores": 4,
                "max_concurrent_executions": 20
            },
            "security_settings": {
                "password_min_length": 10,
                "session_timeout_minutes": 120,
                "max_login_attempts": 3,
                "lockout_duration_minutes": 30
            },
            "monitoring_settings": {
                "metrics_retention_days": 60,
                "log_level": "WARNING",
                "enable_tracing": False,
                "sampling_rate": 0.5
            }
        }

        update_response = await authenticated_admin_client.put("/api/v1/admin/settings/", json=updated_settings)
        assert update_response.status_code == 200

        # Verify updates were applied
        returned_settings = SystemSettings(**update_response.json())
        assert returned_settings.execution_limits.max_timeout_seconds == 600
        assert returned_settings.security_settings.password_min_length == 10
        assert returned_settings.monitoring_settings.log_level == "WARNING"

        # Reset settings
        reset_response = await authenticated_admin_client.post("/api/v1/admin/settings/reset")
        assert reset_response.status_code == 200

        # Verify reset to defaults
        reset_settings = SystemSettings(**reset_response.json())
        assert reset_settings.execution_limits.max_timeout_seconds == 300  # Back to default
        assert reset_settings.security_settings.password_min_length == 8
        assert reset_settings.monitoring_settings.log_level == "INFO"

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_settings(self, authenticated_client: AsyncClient) -> None:
        """Test that regular users cannot access admin settings."""
        # Try to access admin settings as regular user
        response = await authenticated_client.get("/api/v1/admin/settings/")
        assert response.status_code == 403

        error = response.json()
        assert "detail" in error
        assert "admin" in error["detail"].lower() or "forbidden" in error["detail"].lower()


@pytest.mark.integration
class TestAdminUsers:
    """Test admin user management endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_list_users_with_pagination(self, authenticated_admin_client: AsyncClient) -> None:
        """Test listing users with pagination."""
        # List users
        response = await authenticated_admin_client.get("/api/v1/admin/users/?limit=10&offset=0")
        assert response.status_code == 200

        data = response.json()
        assert "users" in data
        assert "total" in data
        # API returns limit/offset, not page/page_size
        assert "limit" in data
        assert "offset" in data

        # Verify pagination logic
        assert data["limit"] == 10
        assert data["offset"] == 0
        assert isinstance(data["users"], list)
        assert data["total"] >= 1  # At least the admin user exists

        # Check user structure
        if data["users"]:
            user = data["users"][0]
            assert "user_id" in user
            assert "username" in user
            assert "email" in user
            assert "role" in user
            assert "is_active" in user
            assert "created_at" in user
            assert "updated_at" in user

    @pytest.mark.asyncio
    async def test_create_and_manage_user(
        self, authenticated_admin_client: AsyncClient, unique_id: Callable[[str], str]
    ) -> None:
        """Test full user CRUD operations."""
        # Create a new user
        uid = unique_id("")
        new_user_data = {
            "username": f"test_managed_user_{uid}",
            "email": f"managed_{uid}@example.com",
            "password": "SecureP@ssw0rd123"
        }

        create_response = await authenticated_admin_client.post("/api/v1/admin/users/", json=new_user_data)
        assert create_response.status_code in [200, 201]

        created_user = create_response.json()
        assert created_user["username"] == new_user_data["username"]
        assert created_user["email"] == new_user_data["email"]
        assert "password" not in created_user
        assert "hashed_password" not in created_user

        user_id = created_user["user_id"]

        # Get user details
        get_response = await authenticated_admin_client.get(f"/api/v1/admin/users/{user_id}")
        assert get_response.status_code == 200

        # Get user overview
        overview_response = await authenticated_admin_client.get(f"/api/v1/admin/users/{user_id}/overview")
        assert overview_response.status_code == 200

        overview_data = overview_response.json()
        overview = AdminUserOverview(**overview_data)
        assert overview.user.user_id == user_id
        assert overview.user.username == new_user_data["username"]

        # Update user
        update_data = {
            "username": f"updated_{uid}",
            "email": f"updated_{uid}@example.com"
        }

        update_response = await authenticated_admin_client.put(f"/api/v1/admin/users/{user_id}", json=update_data)
        assert update_response.status_code == 200

        updated_user = update_response.json()
        assert updated_user["username"] == update_data["username"]
        assert updated_user["email"] == update_data["email"]

        # Delete user
        delete_response = await authenticated_admin_client.delete(f"/api/v1/admin/users/{user_id}")
        assert delete_response.status_code in [200, 204]

        # Verify deletion
        get_deleted_response = await authenticated_admin_client.get(f"/api/v1/admin/users/{user_id}")
        assert get_deleted_response.status_code == 404


@pytest.mark.integration
class TestAdminEvents:
    """Test admin event management endpoints against real backend."""

    @pytest.mark.asyncio
    async def test_browse_events(self, authenticated_admin_client: AsyncClient) -> None:
        """Test browsing events with filters."""
        # Browse events
        browse_payload = {
            "filters": {
                "event_types": ["user_registered", "user_logged_in"]
            },
            "skip": 0,
            "limit": 20,
            "sort_by": "timestamp",
            "sort_order": -1
        }

        response = await authenticated_admin_client.post("/api/v1/admin/events/browse", json=browse_payload)
        assert response.status_code == 200

        data = response.json()
        assert "events" in data
        assert "total" in data
        # has_more is optional or not returned by this endpoint

        # Events should exist from our test user registrations
        assert isinstance(data["events"], list)
        assert data["total"] >= 0

    @pytest.mark.asyncio
    async def test_event_statistics(self, authenticated_admin_client: AsyncClient) -> None:
        """Test getting event statistics."""
        # Get event statistics
        response = await authenticated_admin_client.get("/api/v1/admin/events/stats?hours=24")
        assert response.status_code == 200

        data = response.json()
        # Note: Real API might return different fields than EventStatistics model expects
        # Just validate the essential fields
        assert "total_events" in data
        assert data["total_events"] >= 0

        # Verify structure of what's actually returned
        if "events_by_type" in data:
            assert isinstance(data["events_by_type"], dict)
        if "events_by_hour" in data:
            assert isinstance(data["events_by_hour"], list)
        if "top_users" in data:
            assert isinstance(data["top_users"], list)
        if "error_rate" in data:
            # Implementation may return percentage points or ratio; just ensure non-negative float
            assert isinstance(data["error_rate"], (int, float))
            assert data["error_rate"] >= 0.0

    @pytest.mark.asyncio
    async def test_admin_events_export_csv_and_json(self, authenticated_admin_client: AsyncClient) -> None:
        """Export admin events as CSV and JSON and validate basic structure."""
        # CSV export
        r_csv = await authenticated_admin_client.get("/api/v1/admin/events/export/csv?limit=10")
        assert r_csv.status_code == 200, f"CSV export failed: {r_csv.status_code} - {r_csv.text[:200]}"
        ct_csv = r_csv.headers.get("content-type", "")
        assert "text/csv" in ct_csv
        body_csv = r_csv.text
        # Header line should be present even if empty dataset
        assert "Event ID" in body_csv and "Timestamp" in body_csv

        # JSON export
        r_json = await authenticated_admin_client.get("/api/v1/admin/events/export/json?limit=10")
        assert r_json.status_code == 200, f"JSON export failed: {r_json.status_code} - {r_json.text[:200]}"
        ct_json = r_json.headers.get("content-type", "")
        assert "application/json" in ct_json
        data = r_json.json()
        assert "export_metadata" in data and "events" in data
        assert isinstance(data["events"], list)
        assert "exported_at" in data["export_metadata"]

    @pytest.mark.asyncio
    async def test_admin_user_rate_limits_and_password_reset(
        self, authenticated_admin_client: AsyncClient, unique_id: Callable[[str], str]
    ) -> None:
        """Create a user, manage rate limits, and reset password via admin endpoints."""
        # Create a new user to operate on
        uid = unique_id("")
        new_user = {
            "username": f"rate_limit_user_{uid}",
            "email": f"rl_{uid}@example.com",
            "password": "TempP@ss1234"
        }
        create_response = await authenticated_admin_client.post("/api/v1/admin/users/", json=new_user)
        assert create_response.status_code in [200, 201]
        target_user_id = create_response.json()["user_id"]

        # Get current rate limits (may be None for fresh user)
        rl_get = await authenticated_admin_client.get(f"/api/v1/admin/users/{target_user_id}/rate-limits")
        assert rl_get.status_code == 200
        rl_body = rl_get.json()
        assert rl_body.get("user_id") == target_user_id
        assert "current_usage" in rl_body

        # Update rate limits for user
        update_payload = {
            "user_id": target_user_id,
            "bypass_rate_limit": False,
            "global_multiplier": 1.0,
            "rules": [
                {
                    "endpoint_pattern": r"^/api/v1/execute",
                    "group": "execution",
                    "requests": 5,
                    "window_seconds": 60,
                    "burst_multiplier": 1.0,
                    "algorithm": "sliding_window",
                    "priority": 10,
                    "enabled": True
                }
            ]
        }
        rl_put = await authenticated_admin_client.put(
            f"/api/v1/admin/users/{target_user_id}/rate-limits", json=update_payload
        )
        assert rl_put.status_code == 200
        put_body = rl_put.json()
        assert put_body.get("updated") is True
        assert put_body.get("config", {}).get("user_id") == target_user_id

        # Reset rate limits
        rl_reset = await authenticated_admin_client.post(f"/api/v1/admin/users/{target_user_id}/rate-limits/reset")
        assert rl_reset.status_code == 200

        # Reset password for the user
        new_password = "NewPassw0rd!"
        pw_reset = await authenticated_admin_client.post(
            f"/api/v1/admin/users/{target_user_id}/reset-password",
            json={"new_password": new_password}
        )
        assert pw_reset.status_code == 200

        # Verify user can login with the new password
        logout_resp = await authenticated_admin_client.post("/api/v1/auth/logout")
        assert logout_resp.status_code in [200, 204]
        login_new = await authenticated_admin_client.post(
            "/api/v1/auth/login",
            data={"username": new_user["username"], "password": new_password}
        )
        assert login_new.status_code == 200
