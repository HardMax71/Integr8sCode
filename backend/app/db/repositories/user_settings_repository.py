from datetime import datetime
from typing import Any, Dict, List

from app.core.logging import logger
from app.schemas_pydantic.user import User
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationSettings,
    SettingsHistoryResponse,
    Theme,
    UserSettings,
    UserSettingsUpdate,
)
from app.services.kafka_event_service import KafkaEventService
from app.services.user_settings_service import UserSettingsService


class UserSettingsRepository:
    def __init__(
            self,
            event_service: KafkaEventService,
            settings_service: UserSettingsService
    ):
        self.event_service = event_service
        self.settings_service = settings_service

    async def get_user_settings(self, user_id: str) -> UserSettings:
        try:
            return await self.settings_service.get_user_settings(user_id)
        except Exception as e:
            logger.error(f"Error getting user settings: {e}")
            raise

    async def update_user_settings(
            self,
            user: User,
            updates: UserSettingsUpdate
    ) -> UserSettings:
        try:
            return await self.settings_service.update_user_settings(user, updates)
        except Exception as e:
            logger.error(f"Error updating user settings: {e}")
            raise

    async def update_theme(
            self,
            user: User,
            theme: Theme
    ) -> UserSettings:
        try:
            return await self.settings_service.update_theme(user, theme)
        except Exception as e:
            logger.error(f"Error updating theme: {e}")
            raise

    async def update_notification_settings(
            self,
            user: User,
            notifications: NotificationSettings
    ) -> UserSettings:
        try:
            return await self.settings_service.update_notification_settings(
                user, notifications
            )
        except Exception as e:
            logger.error(f"Error updating notification settings: {e}")
            raise

    async def update_editor_settings(
            self,
            user: User,
            editor: EditorSettings
    ) -> UserSettings:
        try:
            return await self.settings_service.update_editor_settings(user, editor)
        except Exception as e:
            logger.error(f"Error updating editor settings: {e}")
            raise

    async def get_settings_history(
            self,
            user_id: str,
            limit: int = 50
    ) -> List[Dict[str, Any]]:
        try:
            return await self.settings_service.get_settings_history(user_id, limit=limit)
        except Exception as e:
            logger.error(f"Error getting settings history: {e}")
            raise

    async def restore_settings(
            self,
            user: User,
            timestamp: datetime
    ) -> UserSettings:
        try:
            return await self.settings_service.restore_settings_to_point(user, timestamp)
        except Exception as e:
            logger.error(f"Error restoring settings: {e}")
            raise

    async def update_custom_setting(
            self,
            user: User,
            key: str,
            value: Dict[str, Any]
    ) -> UserSettings:
        try:
            return await self.settings_service.update_custom_setting(user, key, value)
        except Exception as e:
            logger.error(f"Error updating custom setting: {e}")
            raise

    def format_settings_history_response(
            self,
            history: List[Dict[str, Any]]
    ) -> SettingsHistoryResponse:
        return SettingsHistoryResponse(
            history=history,
            total=len(history)
        )

    def format_custom_setting_response(
            self,
            key: str,
            settings: UserSettings
    ) -> Dict[str, Any]:
        return {
            "key": key,
            "value": settings.custom_settings.get(key),
            "updated_at": settings.updated_at
        }
