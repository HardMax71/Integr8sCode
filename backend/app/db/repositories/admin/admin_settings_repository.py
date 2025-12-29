import logging
from datetime import datetime, timezone

from app.db.docs import (
    AuditLogDocument,
    ExecutionLimitsConfig,
    MonitoringSettingsConfig,
    SecuritySettingsConfig,
    SystemSettingsDocument,
)
from app.domain.admin import AuditAction


class AdminSettingsRepository:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    async def get_system_settings(self) -> SystemSettingsDocument:
        doc = await SystemSettingsDocument.find_one({"settings_id": "global"})
        if not doc:
            self.logger.info("System settings not found, creating defaults")
            doc = SystemSettingsDocument(
                settings_id="global",
                execution_limits=ExecutionLimitsConfig(),
                security_settings=SecuritySettingsConfig(),
                monitoring_settings=MonitoringSettingsConfig(),
            )
            await doc.insert()
        return doc

    async def update_system_settings(
        self,
        settings: SystemSettingsDocument,
        updated_by: str,
        user_id: str,
    ) -> SystemSettingsDocument:
        settings.updated_at = datetime.now(timezone.utc)
        await settings.save()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            user_id=user_id,
            username=updated_by,
            timestamp=datetime.now(timezone.utc),
            changes=settings.model_dump(exclude={"id", "revision_id"}),
        )
        await audit_entry.insert()

        return settings

    async def reset_system_settings(self, username: str, user_id: str) -> SystemSettingsDocument:
        doc = await SystemSettingsDocument.find_one({"settings_id": "global"})
        if doc:
            await doc.delete()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_RESET,
            user_id=user_id,
            username=username,
            timestamp=datetime.now(timezone.utc),
        )
        await audit_entry.insert()

        return SystemSettingsDocument(
            settings_id="global",
            execution_limits=ExecutionLimitsConfig(),
            security_settings=SecuritySettingsConfig(),
            monitoring_settings=MonitoringSettingsConfig(),
        )
