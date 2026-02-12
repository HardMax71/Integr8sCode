import structlog

from app.db.repositories import AdminSettingsRepository
from app.domain.admin import SystemSettings
from app.services.runtime_settings import RuntimeSettingsLoader


class AdminSettingsService:
    def __init__(
        self,
        repository: AdminSettingsRepository,
        runtime_settings: RuntimeSettingsLoader,
        logger: structlog.stdlib.BoundLogger,
    ):
        self._repo = repository
        self._runtime_settings = runtime_settings
        self.logger = logger

    async def get_system_settings(self, user_id: str) -> SystemSettings:
        self.logger.info(
            "Admin retrieving system settings",
            extra={"user_id": user_id},
        )
        return await self._runtime_settings.get_effective_settings()

    async def update_system_settings(self, settings: SystemSettings, user_id: str) -> SystemSettings:
        self.logger.info(
            "Admin updating system settings",
            extra={"user_id": user_id},
        )
        updated = await self._repo.update_system_settings(settings=settings, user_id=user_id)
        self._runtime_settings.invalidate_cache()
        self.logger.info("System settings updated successfully")
        return updated

    async def reset_system_settings(self, user_id: str) -> SystemSettings:
        self.logger.info(
            "Admin resetting system settings to defaults",
            extra={"user_id": user_id},
        )
        await self._repo.reset_system_settings(user_id=user_id)
        self._runtime_settings.invalidate_cache()
        self.logger.info("System settings reset to defaults")
        return await self._runtime_settings.get_effective_settings()
