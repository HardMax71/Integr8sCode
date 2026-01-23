"""E2E tests for admin settings routes."""

import pytest
from app.schemas_pydantic.admin_settings import (
    ExecutionLimitsSchema,
    MonitoringSettingsSchema,
    SecuritySettingsSchema,
    SystemSettings,
)
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

        # Validate execution limits
        assert settings.execution_limits is not None
        assert isinstance(settings.execution_limits, ExecutionLimitsSchema)
        assert settings.execution_limits.max_timeout_seconds >= 10
        assert settings.execution_limits.max_memory_mb >= 128
        assert settings.execution_limits.max_cpu_cores >= 1
        assert settings.execution_limits.max_concurrent_executions >= 1

        # Validate security settings
        assert settings.security_settings is not None
        assert isinstance(settings.security_settings, SecuritySettingsSchema)
        assert settings.security_settings.password_min_length >= 6
        assert settings.security_settings.session_timeout_minutes >= 5
        assert settings.security_settings.max_login_attempts >= 3
        assert settings.security_settings.lockout_duration_minutes >= 5

        # Validate monitoring settings
        assert settings.monitoring_settings is not None
        assert isinstance(
            settings.monitoring_settings, MonitoringSettingsSchema
        )
        assert settings.monitoring_settings.metrics_retention_days >= 7
        assert settings.monitoring_settings.log_level in [
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        ]
        assert isinstance(settings.monitoring_settings.enable_tracing, bool)
        assert 0.0 <= settings.monitoring_settings.sampling_rate <= 1.0

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
        request = SystemSettings(
            execution_limits=ExecutionLimitsSchema(
                max_timeout_seconds=600,
                max_memory_mb=1024,
                max_cpu_cores=4,
                max_concurrent_executions=20,
            ),
            security_settings=SecuritySettingsSchema(
                password_min_length=10,
                session_timeout_minutes=120,
                max_login_attempts=5,
                lockout_duration_minutes=30,
            ),
            monitoring_settings=MonitoringSettingsSchema(
                metrics_retention_days=60,
                log_level="WARNING",
                enable_tracing=True,
                sampling_rate=0.2,
            ),
        )
        response = await test_admin.put(
            "/api/v1/admin/settings/", json=request.model_dump()
        )

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())

        assert settings.execution_limits.max_timeout_seconds == 600
        assert settings.execution_limits.max_memory_mb == 1024
        assert settings.execution_limits.max_cpu_cores == 4
        assert settings.execution_limits.max_concurrent_executions == 20

        assert settings.security_settings.password_min_length == 10
        assert settings.security_settings.session_timeout_minutes == 120

        assert settings.monitoring_settings.metrics_retention_days == 60
        assert settings.monitoring_settings.log_level == "WARNING"
        assert settings.monitoring_settings.sampling_rate == 0.2

    @pytest.mark.asyncio
    async def test_update_execution_limits_only(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can update only execution limits."""
        # Get current settings first
        get_response = await test_admin.get("/api/v1/admin/settings/")
        current = SystemSettings.model_validate(get_response.json())

        # Update only execution limits
        new_execution_limits = ExecutionLimitsSchema(
            max_timeout_seconds=300,
            max_memory_mb=512,
            max_cpu_cores=2,
            max_concurrent_executions=15,
        )
        request = SystemSettings(
            execution_limits=new_execution_limits,
            security_settings=current.security_settings,
            monitoring_settings=current.monitoring_settings,
        )
        response = await test_admin.put(
            "/api/v1/admin/settings/", json=request.model_dump()
        )

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())
        assert settings.execution_limits.max_timeout_seconds == 300
        assert settings.execution_limits.max_concurrent_executions == 15

    @pytest.mark.asyncio
    async def test_update_security_settings_only(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can update only security settings."""
        # Get current settings
        get_response = await test_admin.get("/api/v1/admin/settings/")
        current = SystemSettings.model_validate(get_response.json())

        # Update only security settings
        new_security = SecuritySettingsSchema(
            password_min_length=12,
            session_timeout_minutes=90,
            max_login_attempts=3,
            lockout_duration_minutes=20,
        )
        request = SystemSettings(
            execution_limits=current.execution_limits,
            security_settings=new_security,
            monitoring_settings=current.monitoring_settings,
        )
        response = await test_admin.put(
            "/api/v1/admin/settings/", json=request.model_dump()
        )

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())
        assert settings.security_settings.password_min_length == 12
        assert settings.security_settings.session_timeout_minutes == 90

    @pytest.mark.asyncio
    async def test_update_monitoring_settings_only(
        self, test_admin: AsyncClient
    ) -> None:
        """Admin can update only monitoring settings."""
        # Get current settings
        get_response = await test_admin.get("/api/v1/admin/settings/")
        current = SystemSettings.model_validate(get_response.json())

        # Update only monitoring settings
        new_monitoring = MonitoringSettingsSchema(
            metrics_retention_days=45,
            log_level="DEBUG",
            enable_tracing=False,
            sampling_rate=0.5,
        )
        request = SystemSettings(
            execution_limits=current.execution_limits,
            security_settings=current.security_settings,
            monitoring_settings=new_monitoring,
        )
        response = await test_admin.put(
            "/api/v1/admin/settings/", json=request.model_dump()
        )

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())
        assert settings.monitoring_settings.metrics_retention_days == 45
        assert settings.monitoring_settings.log_level == "DEBUG"
        assert settings.monitoring_settings.enable_tracing is False
        assert settings.monitoring_settings.sampling_rate == 0.5

    @pytest.mark.asyncio
    async def test_update_system_settings_invalid_values(
        self, test_admin: AsyncClient
    ) -> None:
        """Invalid setting values are rejected."""
        # Get current settings for partial update
        get_response = await test_admin.get("/api/v1/admin/settings/")
        current = SystemSettings.model_validate(get_response.json())

        # Try with invalid timeout (too low)
        response = await test_admin.put(
            "/api/v1/admin/settings/",
            json={
                "execution_limits": {
                    "max_timeout_seconds": 1,  # minimum is 10
                    "max_memory_mb": 512,
                    "max_cpu_cores": 2,
                    "max_concurrent_executions": 10,
                },
                "security_settings": current.security_settings.model_dump(),
                "monitoring_settings": current.monitoring_settings.model_dump(),
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_system_settings_invalid_log_level(
        self, test_admin: AsyncClient
    ) -> None:
        """Invalid log level is rejected."""
        # Get current settings
        get_response = await test_admin.get("/api/v1/admin/settings/")
        current = SystemSettings.model_validate(get_response.json())

        response = await test_admin.put(
            "/api/v1/admin/settings/",
            json={
                "execution_limits": current.execution_limits.model_dump(),
                "security_settings": current.security_settings.model_dump(),
                "monitoring_settings": {
                    "metrics_retention_days": 30,
                    "log_level": "INVALID_LEVEL",  # invalid
                    "enable_tracing": True,
                    "sampling_rate": 0.1,
                },
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_system_settings_forbidden_for_regular_user(
        self, test_user: AsyncClient
    ) -> None:
        """Regular user cannot update system settings."""
        response = await test_user.put(
            "/api/v1/admin/settings/",
            json={
                "execution_limits": {
                    "max_timeout_seconds": 300,
                    "max_memory_mb": 512,
                    "max_cpu_cores": 2,
                    "max_concurrent_executions": 10,
                },
                "security_settings": {
                    "password_min_length": 8,
                    "session_timeout_minutes": 60,
                    "max_login_attempts": 5,
                    "lockout_duration_minutes": 15,
                },
                "monitoring_settings": {
                    "metrics_retention_days": 30,
                    "log_level": "INFO",
                    "enable_tracing": True,
                    "sampling_rate": 0.1,
                },
            },
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
                "execution_limits": {
                    "max_timeout_seconds": 600,
                    "max_memory_mb": 2048,
                    "max_cpu_cores": 8,
                    "max_concurrent_executions": 50,
                },
                "security_settings": {
                    "password_min_length": 16,
                    "session_timeout_minutes": 240,
                    "max_login_attempts": 10,
                    "lockout_duration_minutes": 60,
                },
                "monitoring_settings": {
                    "metrics_retention_days": 90,
                    "log_level": "DEBUG",
                    "enable_tracing": False,
                    "sampling_rate": 0.9,
                },
            },
        )

        # Reset to defaults
        response = await test_admin.post("/api/v1/admin/settings/reset")

        assert response.status_code == 200
        settings = SystemSettings.model_validate(response.json())

        # Check that settings are reset to defaults
        assert settings.execution_limits.max_timeout_seconds == 300
        assert settings.execution_limits.max_memory_mb == 512
        assert settings.execution_limits.max_cpu_cores == 2
        assert settings.execution_limits.max_concurrent_executions == 10

        assert settings.security_settings.password_min_length == 8
        assert settings.security_settings.session_timeout_minutes == 60
        assert settings.security_settings.max_login_attempts == 5
        assert settings.security_settings.lockout_duration_minutes == 15

        assert settings.monitoring_settings.metrics_retention_days == 30
        assert settings.monitoring_settings.log_level == "INFO"
        assert settings.monitoring_settings.enable_tracing is True
        assert settings.monitoring_settings.sampling_rate == 0.1

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
