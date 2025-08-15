from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.logging import logger
from app.domain.admin.settings_models import (
    AuditAction,
    AuditLogEntry,
    SystemSettings,
)


class AdminSettingsRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.settings_collection: AsyncIOMotorCollection = self.db.get_collection("system_settings")
        self.audit_log_collection: AsyncIOMotorCollection = self.db.get_collection("audit_log")

    async def get_system_settings(self) -> SystemSettings:
        """Get system settings from database."""
        settings_doc = await self.settings_collection.find_one({"_id": "global"})
        if not settings_doc:
            logger.warning("System settings document not found in database")
            raise ValueError("System settings document not found")
        return SystemSettings.from_dict(settings_doc)

    async def update_system_settings(
            self,
            settings: SystemSettings,
            updated_by: str,
            user_id: str
    ) -> SystemSettings:
        """Update system-wide settings."""
        async with await self.db.client.start_session() as session:
            async with session.start_transaction():
                try:
                    # Update settings metadata
                    settings.updated_by = updated_by
                    settings.updated_at = datetime.now(timezone.utc)

                    # Convert to dict and save
                    settings_dict = settings.to_dict()

                    await self.settings_collection.replace_one(
                        {"_id": "global"},
                        settings_dict,
                        upsert=True,
                        session=session
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
                        audit_entry.to_dict(),
                        session=session
                    )

                    return settings

                except Exception as e:
                    logger.error(f"Error updating system settings: {e}")
                    raise

    async def reset_system_settings(self, username: str, user_id: str) -> SystemSettings:
        """Reset system settings to defaults."""
        try:
            # Delete current settings
            await self.settings_collection.delete_one({"_id": "global"})

            # Create audit log entry
            audit_entry = AuditLogEntry(
                action=AuditAction.SYSTEM_SETTINGS_RESET,
                user_id=user_id,
                username=username,
                timestamp=datetime.now(timezone.utc)
            )

            await self.audit_log_collection.insert_one(audit_entry.to_dict())

            # Return default settings
            return SystemSettings.get_defaults()

        except Exception as e:
            logger.error(f"Error resetting system settings: {e}")
            raise
