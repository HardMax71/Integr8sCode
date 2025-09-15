from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.domain.admin import (
    AuditAction,
    AuditLogEntry,
    SystemSettings,
)
from app.infrastructure.mappers import AuditLogMapper, SettingsMapper


class AdminSettingsRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings_collection: AsyncIOMotorCollection = self.db.get_collection("system_settings")
        self.audit_log_collection: AsyncIOMotorCollection = self.db.get_collection("audit_log")
        self.settings_mapper = SettingsMapper()
        self.audit_mapper = AuditLogMapper()

    async def get_system_settings(self) -> SystemSettings:
        """Get system settings from database, creating defaults if not found."""
        settings_doc = await self.settings_collection.find_one({"_id": "global"})
        if not settings_doc:
            logger.info("System settings not found, creating defaults")
            # Create default settings
            default_settings = SystemSettings()
            settings_dict = self.settings_mapper.system_settings_to_dict(default_settings)

            # Insert default settings
            await self.settings_collection.insert_one(settings_dict)
            return default_settings

        return self.settings_mapper.system_settings_from_dict(settings_doc)

    async def update_system_settings(
            self,
            settings: SystemSettings,
            updated_by: str,
            user_id: str
    ) -> SystemSettings:
        """Update system-wide settings."""
        # Update settings metadata
        settings.updated_at = datetime.now(timezone.utc)

        # Convert to dict and save
        settings_dict = self.settings_mapper.system_settings_to_dict(settings)

        await self.settings_collection.replace_one(
            {"_id": "global"},
            settings_dict,
            upsert=True
        )

        # Create audit log entry
        audit_entry = AuditLogEntry(
            action=AuditAction.SYSTEM_SETTINGS_UPDATED,
            user_id=user_id,
            username=updated_by,
            timestamp=datetime.now(timezone.utc),
            changes=settings_dict
        )

        await self.audit_log_collection.insert_one(
            self.audit_mapper.to_dict(audit_entry)
        )

        return settings

    async def reset_system_settings(self, username: str, user_id: str) -> SystemSettings:
        """Reset system settings to defaults."""
        # Delete current settings
        await self.settings_collection.delete_one({"_id": "global"})

        # Create audit log entry
        audit_entry = AuditLogEntry(
            action=AuditAction.SYSTEM_SETTINGS_RESET,
            user_id=user_id,
            username=username,
            timestamp=datetime.now(timezone.utc)
        )

        await self.audit_log_collection.insert_one(self.audit_mapper.to_dict(audit_entry))

        # Return default settings
        return SystemSettings()
