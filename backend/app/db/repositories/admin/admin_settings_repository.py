import dataclasses
from datetime import datetime, timezone

import structlog

from app.db.docs.admin_settings import AuditLogDocument, SystemSettingsDocument
from app.domain.admin import AuditAction, SystemSettings
from app.schemas_pydantic.admin_settings import SystemSettingsSchema


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
            doc = SystemSettingsDocument(config=SystemSettingsSchema(**dataclasses.asdict(defaults)))
            await doc.insert()
        return SystemSettings(**doc.config.model_dump())

    async def update_system_settings(self, settings: SystemSettings, user_id: str) -> SystemSettings:
        doc = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global")
        if not doc:
            doc = SystemSettingsDocument()

        doc.config = SystemSettingsSchema(**dataclasses.asdict(settings))
        doc.updated_at = datetime.now(timezone.utc)
        await doc.save()

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            user_id=user_id,
            changes=dataclasses.asdict(settings),
        )
        await audit_entry.insert()

        return SystemSettings(**doc.config.model_dump())

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
