"""E2E tests for admin settings routes."""

import pytest
from app.domain.admin import SystemSettings
from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.admin]


class TestGetSystemSettings:
    """Tests for GET /api/v1/admin/settings/."""

    @pytest.mark.asyncio
    async def test_get_system_settings(self, test_admin: AsyncClient) -> None:
        """Admin can get system settings."""
        response = await test_admin.get("/api/v1/admin/settings/")

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())

        assert settings.max_timeout_seconds >= 1
        assert settings.max_concurrent_executions >= 1
        assert settings.password_min_length >= 8
        assert settings.session_timeout_minutes >= 5
        assert settings.max_login_attempts >= 3
        assert settings.lockout_duration_minutes >= 5
        assert settings.metrics_retention_days >= 7
        assert settings.log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        assert 0.0 <= settings.sampling_rate <= 1.0

    @pytest.mark.asyncio
    async def test_get_system_settings_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot get system settings."""
        response = await test_user.get("/api/v1/admin/settings/")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_system_settings_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/admin/settings/")
        assert response.status_code == 401


class TestUpdateSystemSettings:
    """Tests for PUT /api/v1/admin/settings/."""

    @pytest.mark.asyncio
    async def test_update_system_settings_full(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can update all system settings."""
        request_body = {
            "max_timeout_seconds": 600,
            "memory_limit": "1024Mi",
            "cpu_limit": "4000m",
            "max_concurrent_executions": 20,
            "password_min_length": 10,
            "session_timeout_minutes": 120,
            "max_login_attempts": 5,
            "lockout_duration_minutes": 30,
            "metrics_retention_days": 60,
            "log_level": "WARNING",
            "enable_tracing": True,
            "sampling_rate": 0.2,
        }
        response = await test_admin.put("/api/v1/admin/settings/", json=request_body)

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())

        assert settings.max_timeout_seconds == 600
        assert settings.memory_limit == "1024Mi"
        assert settings.cpu_limit == "4000m"
        assert settings.max_concurrent_executions == 20
        assert settings.password_min_length == 10
        assert settings.session_timeout_minutes == 120
        assert settings.metrics_retention_days == 60
        assert settings.log_level == "WARNING"
        assert settings.sampling_rate == 0.2

    @pytest.mark.asyncio
    async def test_update_partial_fields(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can update a subset of fields (others keep defaults)."""
        request_body = {
            "max_timeout_seconds": 120,
            "max_concurrent_executions": 15,
        }
        response = await test_admin.put("/api/v1/admin/settings/", json=request_body)

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())
        assert settings.max_timeout_seconds == 120
        assert settings.max_concurrent_executions == 15

    @pytest.mark.asyncio
    async def test_update_system_settings_invalid_values(
        self, test_admin: AsyncClient
    ) -> None:
        """Invalid setting values are rejected."""
        response = await test_admin.put(
            "/api/v1/admin/settings/",
            json={"max_timeout_seconds": 0},  # minimum is 1
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_system_settings_invalid_log_level(
        self, test_admin: AsyncClient
    ) -> None:
        """Invalid log level is rejected."""
        response = await test_admin.put(
            "/api/v1/admin/settings/",
            json={"log_level": "INVALID_LEVEL"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_system_settings_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot update system settings."""
        response = await test_user.put(
            "/api/v1/admin/settings/",
            json={"max_timeout_seconds": 300},
        )
        assert response.status_code == 403


class TestResetSystemSettings:
    """Tests for POST /api/v1/admin/settings/reset."""

    @pytest.mark.asyncio
    async def test_reset_system_settings(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can reset system settings to defaults."""
        # First modify settings
        await test_admin.put(
            "/api/v1/admin/settings/",
            json={
                "max_timeout_seconds": 600,
                "memory_limit": "2048Mi",
                "cpu_limit": "8000m",
                "max_concurrent_executions": 50,
                "password_min_length": 16,
                "session_timeout_minutes": 240,
                "max_login_attempts": 10,
                "lockout_duration_minutes": 60,
                "metrics_retention_days": 90,
                "log_level": "DEBUG",
                "enable_tracing": False,
                "sampling_rate": 0.9,
            },
        )

        # Reset to defaults
        response = await test_admin.post("/api/v1/admin/settings/reset")

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())

        assert settings.max_timeout_seconds == 300
        assert settings.memory_limit == "512Mi"
        assert settings.cpu_limit == "2000m"
        assert settings.max_concurrent_executions == 10
        assert settings.password_min_length == 8
        assert settings.session_timeout_minutes == 60
        assert settings.max_login_attempts == 5
        assert settings.lockout_duration_minutes == 15
        assert settings.metrics_retention_days == 30
        assert settings.log_level == "INFO"
        assert settings.enable_tracing is True
        assert settings.sampling_rate == 0.1

    @pytest.mark.asyncio
    async def test_reset_system_settings_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot reset system settings."""
        response = await test_user.post("/api/v1/admin/settings/reset")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_reset_system_settings_unauthenticated(
        self, client: AsyncClient
    ) -> None:
        """Unauthenticated request returns 401."""
        response = await client.post("/api/v1/admin/settings/reset")
        assert response.status_code == 401
