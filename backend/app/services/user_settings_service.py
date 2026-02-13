from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from cachetools import TTLCache

from app.db.repositories import UserSettingsRepository
from app.domain.enums import EventType, Theme
from app.domain.events import EventMetadata, UserSettingsUpdatedEvent
from app.domain.user import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsChangedEvent,
    DomainUserSettingsUpdate,
)
from app.services.kafka_event_service import KafkaEventService
from app.settings import Settings


class UserSettingsService:
    def __init__(
        self,
        repository: UserSettingsRepository,
        event_service: KafkaEventService,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self.repository = repository
        self.event_service = event_service
        self.settings = settings
        self.logger = logger
        self._cache_ttl = timedelta(minutes=5)
        self._max_cache_size = 1000
        self._cache: TTLCache[str, DomainUserSettings] = TTLCache(
            maxsize=self._max_cache_size,
            ttl=self._cache_ttl.total_seconds(),
        )

        self.logger.info(
            "UserSettingsService initialized",
            extra={"cache_ttl_seconds": self._cache_ttl.total_seconds(), "max_cache_size": self._max_cache_size},
        )

    async def get_user_settings(self, user_id: str) -> DomainUserSettings:
        """Get settings with cache; rebuild and cache on miss."""
        if user_id in self._cache:
            cached = self._cache[user_id]
            self.logger.debug(f"Settings cache hit for user {user_id}", extra={"cache_size": len(self._cache)})
            return cached

        return await self.get_user_settings_fresh(user_id)

    async def get_user_settings_fresh(self, user_id: str) -> DomainUserSettings:
        """Bypass cache and rebuild settings from snapshot + events."""
        snapshot = await self.repository.get_snapshot(user_id)

        settings: DomainUserSettings
        event_types = [EventType.USER_SETTINGS_UPDATED]
        if snapshot:
            settings = snapshot
            events = await self.repository.get_settings_events(user_id, event_types, since=snapshot.updated_at)
        else:
            settings = DomainUserSettings(user_id=user_id)
            events = await self.repository.get_settings_events(user_id, event_types)

        for event in events:
            settings = self._apply_event(settings, event)

        self._add_to_cache(user_id, settings)
        return settings

    async def update_user_settings(
        self, user_id: str, updates: DomainUserSettingsUpdate, reason: str | None = None
    ) -> DomainUserSettings:
        """Upsert provided fields into current settings, publish minimal event, and cache."""
        current = await self.get_user_settings(user_id)

        changes = updates.model_dump(exclude_none=True)
        if not changes:
            return current

        new_settings = DomainUserSettings.model_validate({
            **current.model_dump(),
            **changes,
            "version": (current.version or 0) + 1,
            "updated_at": datetime.now(timezone.utc),
        })

        await self._publish_settings_event(user_id, updates.model_dump(exclude_none=True, mode="json"), reason)

        self._add_to_cache(user_id, new_settings)
        if (await self.repository.count_events_since_snapshot(user_id)) >= 10:
            await self.repository.create_snapshot(new_settings)
        return new_settings

    async def _publish_settings_event(self, user_id: str, changes: dict[str, Any], reason: str | None) -> None:
        """Publish settings update event with typed payload fields."""
        event = UserSettingsUpdatedEvent(
            aggregate_id=f"user_settings_{user_id}",
            user_id=user_id,
            changed_fields=list(changes.keys()),
            reason=reason,
            metadata=EventMetadata(
                service_name="integr8scode-user-settings",
                service_version="1.0.0",
                user_id=user_id,
            ),
            **changes,
        )
        await self.event_service.publish_event(event, key=f"user_settings_{user_id}")

    async def update_theme(self, user_id: str, theme: Theme) -> DomainUserSettings:
        """Update user's theme preference"""
        return await self.update_user_settings(
            user_id, DomainUserSettingsUpdate(theme=theme), reason="User changed theme"
        )

    async def update_notification_settings(
        self, user_id: str, notifications: DomainNotificationSettings
    ) -> DomainUserSettings:
        """Update notification preferences"""
        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(notifications=notifications),
            reason="User updated notification preferences",
        )

    async def update_editor_settings(self, user_id: str, editor: DomainEditorSettings) -> DomainUserSettings:
        """Update editor preferences"""
        return await self.update_user_settings(
            user_id, DomainUserSettingsUpdate(editor=editor), reason="User updated editor settings"
        )

    async def update_custom_setting(self, user_id: str, key: str, value: Any) -> DomainUserSettings:
        """Update a custom setting"""
        current_settings = await self.get_user_settings(user_id)
        current_settings.custom_settings[key] = value

        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(custom_settings=current_settings.custom_settings),
            reason=f"Custom setting '{key}' updated",
        )

    async def get_settings_history(self, user_id: str, limit: int = 50) -> list[DomainSettingsHistoryEntry]:
        """Get history from changed fields recorded in events."""
        events = await self.repository.get_settings_events(user_id, [EventType.USER_SETTINGS_UPDATED], limit=limit)
        history: list[DomainSettingsHistoryEntry] = []
        for event in events:
            for fld in event.changed_fields:
                history.append(
                    DomainSettingsHistoryEntry(
                        timestamp=event.timestamp,
                        event_type=event.event_type,
                        field=f"/{fld}",
                        old_value=None,
                        new_value=event.model_dump().get(fld),
                        reason=event.reason,
                    )
                )
        return history

    async def restore_settings_to_point(self, user_id: str, timestamp: datetime) -> DomainUserSettings:
        """Restore settings to a specific point in time"""
        events = await self.repository.get_settings_events(user_id, [EventType.USER_SETTINGS_UPDATED], until=timestamp)

        settings = DomainUserSettings(user_id=user_id)
        for event in events:
            settings = self._apply_event(settings, event)

        await self.repository.create_snapshot(settings)
        self._add_to_cache(user_id, settings)

        restore_event = UserSettingsUpdatedEvent(
            aggregate_id=f"user_settings_{user_id}",
            user_id=user_id,
            changed_fields=[],
            reason=f"Settings restored to {timestamp.isoformat()}",
            metadata=EventMetadata(
                service_name="integr8scode-user-settings",
                service_version="1.0.0",
                user_id=user_id,
            ),
        )
        await self.event_service.publish_event(restore_event, key=f"user_settings_{user_id}")

        return settings

    def _apply_event(self, settings: DomainUserSettings, event: DomainUserSettingsChangedEvent) -> DomainUserSettings:
        """Apply a settings update event via dict merge + model_validate."""
        return DomainUserSettings.model_validate(
            {**settings.model_dump(), **event.model_dump(exclude_none=True), "updated_at": event.timestamp}
        )

    async def invalidate_cache(self, user_id: str) -> None:
        """Invalidate cached settings for a user."""
        if self._cache.pop(user_id, None) is not None:
            self.logger.debug(f"Invalidated cache for user {user_id}", extra={"cache_size": len(self._cache)})

    def _add_to_cache(self, user_id: str, settings: DomainUserSettings) -> None:
        """Add settings to TTL+LRU cache."""
        self._cache[user_id] = settings
        self.logger.debug(f"Cached settings for user {user_id}", extra={"cache_size": len(self._cache)})

    async def reset_user_settings(self, user_id: str) -> None:
        """Reset user settings by deleting all data and cache."""
        await self.invalidate_cache(user_id)
        await self.repository.delete_user_settings(user_id)
        self.logger.info(f"Reset settings for user {user_id}")
