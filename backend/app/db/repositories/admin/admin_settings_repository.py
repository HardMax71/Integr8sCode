import logging
from datetime import datetime, timezone

from app.db.docs import (
    AuditLogDocument,
    ExecutionLimitsConfig,
    MonitoringSettingsConfig,
    SecuritySettingsConfig,
    SystemSettingsDocument,
)
from app.domain.admin import AuditAction, ExecutionLimits, MonitoringSettings, SecuritySettings, SystemSettings


class AdminSettingsRepository:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    async def get_system_settings(self) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if not doc:
            self.logger.info("System settings not found, creating defaults")
            doc = SystemSettingsDocument(
                settings_id="global",
                execution_limits=ExecutionLimitsConfig(),
                security_settings=SecuritySettingsConfig(),
                monitoring_settings=MonitoringSettingsConfig(),
            )
            await doc.insert()
        return SystemSettings(
            execution_limits=ExecutionLimits(**doc.execution_limits.model_dump()),
            security_settings=SecuritySettings(**doc.security_settings.model_dump()),
            monitoring_settings=MonitoringSettings(**doc.monitoring_settings.model_dump()),
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )

    async def update_system_settings(
        self,
        settings: SystemSettings,
        updated_by: str,
        user_id: str,
    ) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if not doc:
            doc = SystemSettingsDocument(settings_id="global")

        doc.execution_limits = ExecutionLimitsConfig(**settings.execution_limits.__dict__)
        doc.security_settings = SecuritySettingsConfig(**settings.security_settings.__dict__)
        doc.monitoring_settings = MonitoringSettingsConfig(**settings.monitoring_settings.__dict__)
        doc.updated_at = datetime.now(timezone.utc)
        await doc.save()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            user_id=user_id,
            username=updated_by,
            timestamp=datetime.now(timezone.utc),
            changes=doc.model_dump(exclude={"id", "revision_id"}),
        )
        await audit_entry.insert()

        return SystemSettings(
            execution_limits=ExecutionLimits(**doc.execution_limits.model_dump()),
            security_settings=SecuritySettings(**doc.security_settings.model_dump()),
            monitoring_settings=MonitoringSettings(**doc.monitoring_settings.model_dump()),
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )

    async def reset_system_settings(self, username: str, user_id: str) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if doc:
            await doc.delete()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_RESET,
            user_id=user_id,
            username=username,
            timestamp=datetime.now(timezone.utc),
        )
        await audit_entry.insert()

        return SystemSettings()
