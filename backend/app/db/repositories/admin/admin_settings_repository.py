from datetime import datetime, timezone

import structlog

from app.db.docs.admin_settings import AuditLogDocument, SystemSettingsDocument
from app.domain.admin import AuditAction, SystemSettings


class AdminSettingsRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    async def get_system_settings(
        self,
        defaults: SystemSettings,
    ) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if not doc:
            self.logger.info("System settings not found, creating defaults")
            doc = SystemSettingsDocument(config=defaults)
            await doc.insert()
        return doc.config

    async def update_system_settings(self, settings: SystemSettings, user_id: str) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if not doc:
            doc = SystemSettingsDocument()

        doc.config = settings
        doc.updated_at = datetime.now(timezone.utc)
        await doc.save()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            user_id=user_id,
            changes=settings.model_dump(),
        )
        await audit_entry.insert()

        return doc.config

    async def reset_system_settings(self, user_id: str) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if doc:
            await doc.delete()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_RESET,
            user_id=user_id,
        )
        await audit_entry.insert()

        return SystemSettings()
