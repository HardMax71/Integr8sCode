import logging

from app.db.repositories import AdminSettingsRepository
from app.domain.admin import SystemSettings
from app.services.runtime_settings import RuntimeSettingsLoader


class AdminSettingsService:
    def __init__(
        self,
        repository: AdminSettingsRepository,
        runtime_settings: RuntimeSettingsLoader,
        logger: logging.Logger,
    ):
        self._repo = repository
        self._runtime_settings = runtime_settings
        self.logger = logger

    async def get_system_settings(self, admin_username: str) -> SystemSettings:
        self.logger.info(
            "Admin retrieving system settings",
            extra={"admin_username": admin_username},
        )
        return await self._runtime_settings.get_effective_settings()

    async def update_system_settings(
        self,
        settings: SystemSettings,
        updated_by: str,
        user_id: str,
    ) -> SystemSettings:
        self.logger.info(
            "Admin updating system settings",
            extra={"admin_username": updated_by},
        )
        updated = await self._repo.update_system_settings(settings=settings, updated_by=updated_by, user_id=user_id)
        self._runtime_settings.invalidate_cache()
        self.logger.info("System settings updated successfully")
        return updated

    async def reset_system_settings(self, username: str, user_id: str) -> SystemSettings:
        self.logger.info(
            "Admin resetting system settings to defaults",
            extra={"admin_username": username},
        )
        await self._repo.reset_system_settings(username=username, user_id=user_id)
        self._runtime_settings.invalidate_cache()
        self.logger.info("System settings reset to defaults")
        return await self._runtime_settings.get_effective_settings()
