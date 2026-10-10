import dataclasses
from datetime import datetime, timezone

import structlog
from beanie.odm.queries.update import UpdateResponse

from app.db.docs.admin_settings import AuditLogDocument, SystemSettingsDocument
from app.domain.admin import AuditAction, SystemSettings


class AdminSettingsRepository:
    def __init__(self, logger: structlog.stdlib.BoundLogger):
        self.logger = logger

    async def get_system_settings(
        self,
        defaults: SystemSettings,
    ) -> SystemSettings:
        insert_data = SystemSettingsDocument(config=defaults).model_dump(exclude={"id", "revision_id"})
        existing = await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global").update(
            {"$setOnInsert": insert_data},
            upsert=True,
            response_type=UpdateResponse.OLD_DOCUMENT,
        )
        if not isinstance(existing, SystemSettingsDocument):
            self.logger.info("System settings not found, created defaults")
            return defaults
        return existing.config

    async def update_system_settings(self, settings: SystemSettings, user_id: str) -> SystemSettings:
        now = datetime.now(timezone.utc)
        await SystemSettingsDocument.find_one(SystemSettingsDocument.settings_id == "global").update(
            {"$set": {"config": settings, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

        audit_entry = AuditLogDocument(
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            user_id=user_id,
            changes=dataclasses.asdict(settings),
        )
        await audit_entry.insert()

        return settings

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
