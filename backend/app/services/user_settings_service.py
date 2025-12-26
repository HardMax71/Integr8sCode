import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, List

from cachetools import TTLCache

from app.core.logging import logger
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.domain.enums import Theme
from app.domain.enums.auth import SettingsType
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationChannel
from app.domain.user import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsEvent,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsUpdate,
)
from app.services.event_bus import EventBusEvent, EventBusManager
from app.services.kafka_event_service import KafkaEventService


class UserSettingsService:
    def __init__(self, repository: UserSettingsRepository, event_service: KafkaEventService) -> None:
        self.repository = repository
        self.event_service = event_service
        # TTL+LRU cache for settings
        self._cache_ttl = timedelta(minutes=5)
        self._max_cache_size = 1000
        self._cache: TTLCache[str, DomainUserSettings] = TTLCache(
            maxsize=self._max_cache_size,
            ttl=self._cache_ttl.total_seconds(),
        )
        self._event_bus_manager: EventBusManager | None = None
        self._subscription_id: str | None = None

        logger.info(
            "UserSettingsService initialized",
            extra={"cache_ttl_seconds": self._cache_ttl.total_seconds(), "max_cache_size": self._max_cache_size},
        )

    async def get_user_settings(self, user_id: str) -> DomainUserSettings:
        """Get settings with cache; rebuild and cache on miss."""
        if user_id in self._cache:
            cached = self._cache[user_id]
            logger.debug(f"Settings cache hit for user {user_id}", extra={"cache_size": len(self._cache)})
            return cached

        return await self.get_user_settings_fresh(user_id)

    async def initialize(self, event_bus_manager: EventBusManager) -> None:
        """Subscribe to settings update events for cache invalidation."""
        self._event_bus_manager = event_bus_manager
        bus = await event_bus_manager.get_event_bus()

        async def _handle(evt: EventBusEvent) -> None:
            uid = evt.payload.get("user_id")
            if uid:
                # Use asyncio.to_thread for the sync operation to make it properly async
                await asyncio.to_thread(self.invalidate_cache, str(uid))

        self._subscription_id = await bus.subscribe("user.settings.updated*", _handle)

    async def get_user_settings_fresh(self, user_id: str) -> DomainUserSettings:
        """Bypass cache and rebuild settings from snapshot + events."""
        snapshot = await self.repository.get_snapshot(user_id)

        if snapshot:
            settings = snapshot
            events = await self._get_settings_events(user_id, since=snapshot.updated_at)
        else:
            settings = DomainUserSettings(user_id=user_id)
            events = await self._get_settings_events(user_id)

        for event in events:
            settings = self._apply_event(settings, event)

        self._add_to_cache(user_id, settings)
        return settings

    async def update_user_settings(
        self, user_id: str, updates: DomainUserSettingsUpdate, reason: str | None = None
    ) -> DomainUserSettings:
        """Upsert provided fields into current settings, publish minimal event, and cache."""
        s = await self.get_user_settings(user_id)
        updated: dict[str, object] = {}
        old_theme = s.theme
        # Top-level
        if updates.theme is not None:
            s.theme = updates.theme
            updated["theme"] = str(updates.theme)
        if updates.timezone is not None:
            s.timezone = updates.timezone
            updated["timezone"] = updates.timezone
        if updates.date_format is not None:
            s.date_format = updates.date_format
            updated["date_format"] = updates.date_format
        if updates.time_format is not None:
            s.time_format = updates.time_format
            updated["time_format"] = updates.time_format
        # Nested
        if updates.notifications is not None:
            n = updates.notifications
            s.notifications = n
            updated["notifications"] = {
                "execution_completed": n.execution_completed,
                "execution_failed": n.execution_failed,
                "system_updates": n.system_updates,
                "security_alerts": n.security_alerts,
                "channels": [str(c) for c in n.channels],
            }
        if updates.editor is not None:
            e = updates.editor
            s.editor = e
            updated["editor"] = {
                "theme": e.theme,
                "font_size": e.font_size,
                "tab_size": e.tab_size,
                "use_tabs": e.use_tabs,
                "word_wrap": e.word_wrap,
                "show_line_numbers": e.show_line_numbers,
            }
        if updates.custom_settings is not None:
            s.custom_settings = updates.custom_settings
            updated["custom_settings"] = updates.custom_settings

        if not updated:
            return s

        s.updated_at = datetime.now(timezone.utc)
        s.version = (s.version or 0) + 1

        # Choose appropriate event payload
        if "theme" in updated and len(updated) == 1:
            await self.event_service.publish_event(
                event_type=EventType.USER_THEME_CHANGED,
                aggregate_id=f"user_settings_{user_id}",
                payload={
                    "user_id": user_id,
                    "old_theme": str(old_theme),
                    "new_theme": str(s.theme),
                    "reason": reason,
                },
                metadata=None,
            )
        elif "notifications" in updated and len(updated) == 1:
            # Only notification settings changed
            notif = updated["notifications"]
            channels = notif.pop("channels", None) if isinstance(notif, dict) else None
            await self.event_service.publish_event(
                event_type=EventType.USER_NOTIFICATION_SETTINGS_UPDATED,
                aggregate_id=f"user_settings_{user_id}",
                payload={
                    "user_id": user_id,
                    "settings": notif,
                    "channels": channels,
                    "reason": reason,
                },
                metadata=None,
            )
        elif "editor" in updated and len(updated) == 1:
            # Only editor settings changed
            await self.event_service.publish_event(
                event_type=EventType.USER_EDITOR_SETTINGS_UPDATED,
                aggregate_id=f"user_settings_{user_id}",
                payload={
                    "user_id": user_id,
                    "settings": updated["editor"],
                    "reason": reason,
                },
                metadata=None,
            )
        else:
            # Multiple fields changed or other fields
            if "notifications" in updated:
                settings_type = SettingsType.NOTIFICATION
            elif "editor" in updated:
                settings_type = SettingsType.EDITOR
            elif "theme" in updated:
                settings_type = SettingsType.DISPLAY
            else:
                settings_type = SettingsType.PREFERENCES
            # Flatten changes to string map for the generic event
            changes: dict[str, str] = {}
            for k, v in updated.items():
                changes[k] = str(v)
            await self.event_service.publish_event(
                event_type=EventType.USER_SETTINGS_UPDATED,
                aggregate_id=f"user_settings_{user_id}",
                payload={
                    "user_id": user_id,
                    "settings_type": settings_type,
                    "changes": changes,
                    "reason": reason,
                },
                metadata=None,
            )

        if self._event_bus_manager is not None:
            bus = await self._event_bus_manager.get_event_bus()
            await bus.publish("user.settings.updated", {"user_id": user_id})

        self._add_to_cache(user_id, s)
        if (await self.repository.count_events_since_snapshot(user_id)) >= 10:
            await self.repository.create_snapshot(s)
        return s

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

    async def get_settings_history(self, user_id: str, limit: int = 50) -> List[DomainSettingsHistoryEntry]:
        """Get history from changed paths recorded in events."""
        events = await self._get_settings_events(user_id, limit=limit)
        history: list[DomainSettingsHistoryEntry] = []
        for event in events:
            if event.event_type == EventType.USER_THEME_CHANGED:
                history.append(
                    DomainSettingsHistoryEntry(
                        timestamp=event.timestamp,
                        event_type=event.event_type,
                        field="/theme",
                        old_value=event.payload.get("old_theme"),
                        new_value=event.payload.get("new_theme"),
                        reason=event.payload.get("reason"),
                        correlation_id=event.correlation_id,
                    )
                )
                continue

            upd = event.payload.get("updated", {})
            if not upd:
                continue
            for path in (f"/{k}" for k in upd.keys()):
                history.append(
                    DomainSettingsHistoryEntry(
                        timestamp=event.timestamp,
                        event_type=event.event_type,
                        field=path,
                        old_value=None,
                        new_value=None,
                        reason=event.payload.get("reason"),
                        correlation_id=event.correlation_id,
                    )
                )
        return history

    async def restore_settings_to_point(self, user_id: str, timestamp: datetime) -> DomainUserSettings:
        """Restore settings to a specific point in time"""
        # Get all events up to the timestamp
        events = await self._get_settings_events(user_id, until=timestamp)

        # Rebuild settings from events
        settings = DomainUserSettings(user_id=user_id)
        for event in events:
            settings = self._apply_event(settings, event)

        # Save as current settings
        await self.repository.create_snapshot(settings)
        self._add_to_cache(user_id, settings)

        # Publish restoration event (generic settings update form)
        await self.event_service.publish_event(
            event_type=EventType.USER_SETTINGS_UPDATED,
            aggregate_id=f"user_settings_{user_id}",
            payload={
                "user_id": user_id,
                "settings_type": SettingsType.PREFERENCES,
                "changes": {"restored_to": timestamp.isoformat()},
            },
            metadata=None,
        )

        return settings

    async def _get_settings_events(
        self, user_id: str, since: datetime | None = None, until: datetime | None = None, limit: int | None = None
    ) -> List[DomainSettingsEvent]:
        """Get settings-related events for a user"""
        event_types = [
            EventType.USER_SETTINGS_UPDATED,
            EventType.USER_THEME_CHANGED,
            EventType.USER_NOTIFICATION_SETTINGS_UPDATED,
            EventType.USER_EDITOR_SETTINGS_UPDATED,
        ]

        raw = await self.repository.get_settings_events(
            user_id=user_id, event_types=event_types, since=since, until=until, limit=limit
        )
        # map to domain
        out: list[DomainSettingsEvent] = []
        for e in raw:
            et = EventType(e.event_type)
            out.append(
                DomainSettingsEvent(
                    event_type=et,
                    timestamp=e.timestamp,
                    payload=e.payload,
                    correlation_id=e.correlation_id,
                )
            )
        return out

    def _apply_event(self, settings: DomainUserSettings, event: DomainSettingsEvent) -> DomainUserSettings:
        if event.event_type == EventType.USER_THEME_CHANGED:
            new_theme = event.payload.get("new_theme")
            if new_theme:
                settings.theme = Theme(new_theme)
            return settings

        upd = event.payload.get("updated")
        if not upd:
            return settings

        # Top-level
        if "theme" in upd:
            settings.theme = Theme(upd["theme"])
        if "timezone" in upd:
            settings.timezone = upd["timezone"]
        if "date_format" in upd:
            settings.date_format = upd["date_format"]
        if "time_format" in upd:
            settings.time_format = upd["time_format"]
        # Nested
        if "notifications" in upd and isinstance(upd["notifications"], dict):
            n = upd["notifications"]
            channels: list[NotificationChannel] = [NotificationChannel(c) for c in n.get("channels", [])]
            settings.notifications = DomainNotificationSettings(
                execution_completed=n.get("execution_completed", settings.notifications.execution_completed),
                execution_failed=n.get("execution_failed", settings.notifications.execution_failed),
                system_updates=n.get("system_updates", settings.notifications.system_updates),
                security_alerts=n.get("security_alerts", settings.notifications.security_alerts),
                channels=channels or settings.notifications.channels,
            )
        if "editor" in upd and isinstance(upd["editor"], dict):
            e = upd["editor"]
            settings.editor = DomainEditorSettings(
                theme=e.get("theme", settings.editor.theme),
                font_size=e.get("font_size", settings.editor.font_size),
                tab_size=e.get("tab_size", settings.editor.tab_size),
                use_tabs=e.get("use_tabs", settings.editor.use_tabs),
                word_wrap=e.get("word_wrap", settings.editor.word_wrap),
                show_line_numbers=e.get("show_line_numbers", settings.editor.show_line_numbers),
            )
        if "custom_settings" in upd and isinstance(upd["custom_settings"], dict):
            settings.custom_settings = upd["custom_settings"]
        settings.version = event.payload.get("version", settings.version)
        settings.updated_at = event.timestamp
        return settings

    def invalidate_cache(self, user_id: str) -> None:
        """Invalidate cached settings for a user"""
        removed = self._cache.pop(user_id, None) is not None
        if removed:
            logger.debug(f"Invalidated cache for user {user_id}", extra={"cache_size": len(self._cache)})

    def _add_to_cache(self, user_id: str, settings: DomainUserSettings) -> None:
        """Add settings to TTL+LRU cache."""
        self._cache[user_id] = settings
        logger.debug(f"Cached settings for user {user_id}", extra={"cache_size": len(self._cache)})

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
        # Clear from cache
        self.invalidate_cache(user_id)

        # Delete from database
        await self.repository.delete_user_settings(user_id)

        logger.info(f"Reset settings for user {user_id}")
