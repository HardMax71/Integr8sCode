from app.core.logging import logger
from app.db.repositories.admin.admin_settings_repository import AdminSettingsRepository
from app.domain.admin import SystemSettings


class AdminSettingsService:
    def __init__(self, repository: AdminSettingsRepository):
        self._repo = repository

    async def get_system_settings(self, admin_username: str) -> SystemSettings:
        logger.info(
            "Admin retrieving system settings",
            extra={"admin_username": admin_username},
        )
        settings = await self._repo.get_system_settings()
        return settings

    async def update_system_settings(
            self,
            settings: SystemSettings,
            updated_by: str,
            user_id: str,
    ) -> SystemSettings:
        logger.info(
            "Admin updating system settings",
            extra={"admin_username": updated_by},
        )
        updated = await self._repo.update_system_settings(
            settings=settings, updated_by=updated_by, user_id=user_id
        )
        logger.info("System settings updated successfully")
        return updated

    async def reset_system_settings(self, username: str, user_id: str) -> SystemSettings:
        # Reset (with audit) and return fresh defaults persisted via get
        logger.info(
            "Admin resetting system settings to defaults",
            extra={"admin_username": username},
        )
        await self._repo.reset_system_settings(username=username, user_id=user_id)
        settings = await self._repo.get_system_settings()
        logger.info("System settings reset to defaults")
        return settings
