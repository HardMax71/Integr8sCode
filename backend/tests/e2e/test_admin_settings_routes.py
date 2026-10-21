"""E2E tests for admin settings routes."""

import pytest
from httpx2 import AsyncClient

from app.domain.admin import SystemSettings
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.xdist_group("system_settings")]


class TestGetSystemSettings:
    """Tests for GET /api/v1/admin/settings/."""

    async def test_get_system_settings(self, test_admin: AsyncClient) -> None:
        """Admin can get system settings."""
        response = await test_admin.get("/api/v1/admin/settings/")

        assert response.status_code == 200
        settings = SystemSettings(**response.json())

        assert settings.max_timeout_seconds >= 1
        assert settings.max_concurrent_executions >= 1
        assert settings.password_min_length >= 8
        assert settings.session_timeout_minutes >= 5
        assert settings.max_login_attempts >= 3
        assert settings.lockout_duration_minutes >= 5

    async def test_get_system_settings_forbidden_for_regular_user(self, test_user: AsyncClient) -> None:
        """Regular user cannot get system settings."""
        response = await test_user.get("/api/v1/admin/settings/")
        assert response.status_code == 403

    async def test_get_system_settings_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/admin/settings/")
        assert response.status_code == 401


class TestUpdateSystemSettings:
    """Tests for PUT /api/v1/admin/settings/.

    Settings are global and every process reads them, so these tests change only the lockout duration, since no
    other test depends on it, and send everything else back as it was.
    """

    async def test_update_system_settings(self, test_admin: AsyncClient) -> None:
        """A PUT stores the body and returns it."""
        current = (await test_admin.get("/api/v1/admin/settings/")).json()
        body = {**current, "lockout_duration_minutes": 30}

        response = await test_admin.put("/api/v1/admin/settings/", json=body)

        assert response.status_code == 200
        assert response.json() == body
        assert (await test_admin.get("/api/v1/admin/settings/")).json() == body

    async def test_update_system_settings_invalid_values(self, test_admin: AsyncClient) -> None:
        """Invalid setting values are rejected."""
        response = await test_admin.put(
            "/api/v1/admin/settings/",
            json={"max_timeout_seconds": 0},  # minimum is 1
        )
        assert response.status_code == 422

    async def test_update_system_settings_forbidden_for_regular_user(self, test_user: AsyncClient) -> None:
        """Regular user cannot update system settings."""
        response = await test_user.put(
            "/api/v1/admin/settings/",
            json={"max_timeout_seconds": 300},
        )
        assert response.status_code == 403


class TestResetSystemSettings:
    """Tests for POST /api/v1/admin/settings/reset."""

    async def test_reset_system_settings(self, test_admin: AsyncClient, test_settings: Settings) -> None:
        """Admin can reset system settings to defaults."""
        current = (await test_admin.get("/api/v1/admin/settings/")).json()
        await test_admin.put(
            "/api/v1/admin/settings/",
            json={**current, "lockout_duration_minutes": 45},
        )

        # Reset to defaults
        response = await test_admin.post("/api/v1/admin/settings/reset")

        assert response.status_code == 200
        settings = SystemSettings(**response.json())

        # Reset returns TOML-derived defaults for fields mapped from Settings,
        # and SystemSettings() model defaults for the rest.
        expected = SystemSettings(
            max_timeout_seconds=test_settings.K8S_POD_EXECUTION_TIMEOUT,
            memory_limit=test_settings.K8S_POD_MEMORY_LIMIT,
            cpu_limit=test_settings.K8S_POD_CPU_LIMIT,
            session_timeout_minutes=test_settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        )
        assert settings == expected

    async def test_reset_system_settings_forbidden_for_regular_user(self, test_user: AsyncClient) -> None:
        """Regular user cannot reset system settings."""
        response = await test_user.post("/api/v1/admin/settings/reset")
        assert response.status_code == 403

    async def test_reset_system_settings_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        response = await client.post("/api/v1/admin/settings/reset")
        assert response.status_code == 401
