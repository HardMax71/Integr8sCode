import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from cachetools import TTLCache
from pydantic import TypeAdapter

from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.domain.enums import Theme
from app.domain.enums.events import EventType
from app.domain.user import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsChangedEvent,
    DomainUserSettingsUpdate,
)
from app.services.event_bus import EventBusEvent, EventBusManager
from app.services.kafka_event_service import KafkaEventService

_settings_adapter = TypeAdapter(DomainUserSettings)
_update_adapter = TypeAdapter(DomainUserSettingsUpdate)


class UserSettingsService:
    def __init__(
        self, repository: UserSettingsRepository, event_service: KafkaEventService, logger: logging.Logger
    ) -> None:
        self.repository = repository
        self.event_service = event_service
        self.logger = logger
        self._cache_ttl = timedelta(minutes=5)
        self._max_cache_size = 1000
        self._cache: TTLCache[str, DomainUserSettings] = TTLCache(
            maxsize=self._max_cache_size,
            ttl=self._cache_ttl.total_seconds(),
        )
        self._event_bus_manager: EventBusManager | None = None
        self._subscription_id: str | None = None
        self._instance_id: str = str(uuid4())

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

    async def initialize(self, event_bus_manager: EventBusManager) -> None:
        """Subscribe to settings update events for cross-instance cache invalidation."""
        self._event_bus_manager = event_bus_manager
        bus = await event_bus_manager.get_event_bus()

        async def _handle(evt: EventBusEvent) -> None:
            # Skip events from this instance - we already updated our cache
            if evt.payload.get("source_instance") == self._instance_id:
                return
            uid = evt.payload.get("user_id")
            if uid:
                await self.invalidate_cache(str(uid))

        self._subscription_id = await bus.subscribe("user.settings.updated*", _handle)

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

        changes = _update_adapter.dump_python(updates, exclude_none=True)
        if not changes:
            return current

        current_dict = _settings_adapter.dump_python(current)
        merged = {**current_dict, **changes}
        merged["version"] = (current.version or 0) + 1
        merged["updated_at"] = datetime.now(timezone.utc)

        new_settings = _settings_adapter.validate_python(merged)

        changes_json = _update_adapter.dump_python(updates, exclude_none=True, mode="json")
        await self._publish_settings_event(user_id, changes_json, reason)

        if self._event_bus_manager is not None:
            bus = await self._event_bus_manager.get_event_bus()
            await bus.publish("user.settings.updated", {"user_id": user_id, "source_instance": self._instance_id})

        self._add_to_cache(user_id, new_settings)
        if (await self.repository.count_events_since_snapshot(user_id)) >= 10:
            await self.repository.create_snapshot(new_settings)
        return new_settings

    async def _publish_settings_event(self, user_id: str, changes: dict[str, Any], reason: str | None) -> None:
        """Publish settings update event with typed payload fields."""
        await self.event_service.publish_event(
            event_type=EventType.USER_SETTINGS_UPDATED,
            aggregate_id=f"user_settings_{user_id}",
            payload={
                "user_id": user_id,
                "changed_fields": list(changes.keys()),
                "reason": reason,
                **changes,
            },
            metadata=None,
        )

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
                        correlation_id=event.correlation_id,
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

        await self.event_service.publish_event(
            event_type=EventType.USER_SETTINGS_UPDATED,
            aggregate_id=f"user_settings_{user_id}",
            payload={
                "user_id": user_id,
                "changed_fields": [],
                "reason": f"Settings restored to {timestamp.isoformat()}",
            },
            metadata=None,
        )

        return settings

    _settings_fields = {"theme", "timezone", "date_format", "time_format", "notifications", "editor"}

    def _apply_event(self, settings: DomainUserSettings, event: DomainUserSettingsChangedEvent) -> DomainUserSettings:
        """Apply a settings update event using TypeAdapter merge."""
        event_dict = event.model_dump()
        changes = {k: v for k, v in event_dict.items() if k in self._settings_fields and v is not None}
        if not changes:
            return settings

        current_dict = _settings_adapter.dump_python(settings)
        merged = {**current_dict, **changes}
        merged["updated_at"] = event.timestamp

        return _settings_adapter.validate_python(merged)

    async def invalidate_cache(self, user_id: str) -> None:
        """Invalidate cached settings for a user."""
        if self._cache.pop(user_id, None) is not None:
            self.logger.debug(f"Invalidated cache for user {user_id}", extra={"cache_size": len(self._cache)})

    def _add_to_cache(self, user_id: str, settings: DomainUserSettings) -> None:
        """Add settings to TTL+LRU cache."""
        self._cache[user_id] = settings
        self.logger.debug(f"Cached settings for user {user_id}", extra={"cache_size": len(self._cache)})

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        return {
            "cache_size": len(self._cache),
            "max_cache_size": self._max_cache_size,
            "expired_entries": 0,
            "cache_ttl_seconds": self._cache_ttl.total_seconds(),
        }

    async def reset_user_settings(self, user_id: str) -> None:
        """Reset user settings by deleting all data and cache."""
        await self.invalidate_cache(user_id)
        await self.repository.delete_user_settings(user_id)
        self.logger.info(f"Reset settings for user {user_id}")
