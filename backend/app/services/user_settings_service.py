from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, List

from app.core.logging import logger
from app.db.repositories.user_settings_repository import UserSettingsRepository
from app.domain.enums import Theme
from app.domain.enums.events import EventType
from app.domain.user.settings_models import (
    CachedSettings,
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingChange,
    DomainSettingsEvent,
    DomainSettingsHistoryEntry,
    DomainUserSettings,
    DomainUserSettingsUpdate,
)
from app.services.kafka_event_service import KafkaEventService


class UserSettingsService:
    def __init__(
            self,
            repository: UserSettingsRepository,
            event_service: KafkaEventService
    ) -> None:
        self.repository = repository
        self.event_service = event_service
        # Use OrderedDict for LRU-like behavior
        self._settings_cache: OrderedDict[str, CachedSettings] = OrderedDict()
        self._cache_ttl = timedelta(minutes=5)
        self._max_cache_size = 1000

        logger.info(
            "UserSettingsService initialized",
            extra={
                "cache_ttl_seconds": self._cache_ttl.total_seconds(),
                "max_cache_size": self._max_cache_size
            }
        )

    async def get_user_settings(self, user_id: str) -> DomainUserSettings:
        """Get settings with cache; rebuild and cache on miss."""
        cached = self._get_from_cache(user_id)
        if cached:
            logger.debug(
                f"Settings cache hit for user {user_id}",
                extra={"cache_size": len(self._settings_cache)}
            )
            return cached

        return await self.get_user_settings_fresh(user_id)

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
            self,
            user_id: str,
            updates: DomainUserSettingsUpdate,
            reason: str | None = None
    ) -> DomainUserSettings:
        """Update user settings and publish events"""
        current_settings = await self.get_user_settings(user_id)

        # Track changes and apply explicitly-typed updates
        changes: list[DomainSettingChange] = []
        new_values: dict[str, Any] = {}

        if updates.theme is not None and current_settings.theme != updates.theme:
            changes.append(DomainSettingChange(
                field_path="theme",
                old_value=current_settings.theme,
                new_value=updates.theme,
                change_reason=reason,
            ))
            current_settings.theme = updates.theme
            new_values["theme"] = updates.theme

        if updates.timezone is not None and current_settings.timezone != updates.timezone:
            changes.append(DomainSettingChange(
                field_path="timezone",
                old_value=current_settings.timezone,
                new_value=updates.timezone,
                change_reason=reason,
            ))
            current_settings.timezone = updates.timezone
            new_values["timezone"] = updates.timezone

        if updates.date_format is not None and current_settings.date_format != updates.date_format:
            changes.append(DomainSettingChange(
                field_path="date_format",
                old_value=current_settings.date_format,
                new_value=updates.date_format,
                change_reason=reason,
            ))
            current_settings.date_format = updates.date_format
            new_values["date_format"] = updates.date_format

        if updates.time_format is not None and current_settings.time_format != updates.time_format:
            changes.append(DomainSettingChange(
                field_path="time_format",
                old_value=current_settings.time_format,
                new_value=updates.time_format,
                change_reason=reason,
            ))
            current_settings.time_format = updates.time_format
            new_values["time_format"] = updates.time_format

        if updates.notifications is not None and current_settings.notifications != updates.notifications:
            changes.append(DomainSettingChange(
                field_path="notifications",
                old_value=current_settings.notifications,
                new_value=updates.notifications,
                change_reason=reason,
            ))
            current_settings.notifications = updates.notifications
            new_values["notifications"] = {
                "execution_completed": updates.notifications.execution_completed,
                "execution_failed": updates.notifications.execution_failed,
                "system_updates": updates.notifications.system_updates,
                "security_alerts": updates.notifications.security_alerts,
                "channels": updates.notifications.channels,
            }

        if updates.editor is not None and current_settings.editor != updates.editor:
            changes.append(DomainSettingChange(
                field_path="editor",
                old_value=current_settings.editor,
                new_value=updates.editor,
                change_reason=reason,
            ))
            current_settings.editor = updates.editor
            new_values["editor"] = {
                "theme": updates.editor.theme,
                "font_size": updates.editor.font_size,
                "tab_size": updates.editor.tab_size,
                "use_tabs": updates.editor.use_tabs,
                "word_wrap": updates.editor.word_wrap,
                "show_line_numbers": updates.editor.show_line_numbers,
            }

        if updates.custom_settings is not None and current_settings.custom_settings != updates.custom_settings:
            changes.append(DomainSettingChange(
                field_path="custom_settings",
                old_value=current_settings.custom_settings,
                new_value=updates.custom_settings,
                change_reason=reason,
            ))
            current_settings.custom_settings = updates.custom_settings
            new_values["custom_settings"] = updates.custom_settings

        if not changes:
            return current_settings  # No changes

        # Update timestamp
        current_settings.updated_at = datetime.now(timezone.utc)

        # Publish event based on the updated top-level fields
        event_type = self._determine_event_type_from_fields(set(new_values.keys()))

        await self.event_service.publish_event(
            event_type=event_type,
            aggregate_id=f"user_settings_{user_id}",
            payload={
                "user_id": user_id,
                "changes": [
                    {
                        "field_path": change.field_path,
                        "old_value": change.old_value,
                        "new_value": change.new_value,
                        "changed_at": change.changed_at,
                        "change_reason": change.change_reason,
                    }
                    for change in changes
                ],
                "reason": reason,
                "new_values": new_values
            },
            user_id=None
        )

        # Update cache
        self._add_to_cache(user_id, current_settings)

        # Create snapshot if enough changes accumulated
        event_count = await self.repository.count_events_since_snapshot(user_id)
        if event_count >= 10:  # Snapshot every 10 events
            await self.repository.create_snapshot(current_settings)

        return current_settings

    async def update_theme(self, user_id: str, theme: Theme) -> DomainUserSettings:
        """Update user's theme preference"""
        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(theme=theme),
            reason="User changed theme"
        )

    async def update_notification_settings(
            self,
            user_id: str,
            notifications: DomainNotificationSettings
    ) -> DomainUserSettings:
        """Update notification preferences"""
        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(notifications=notifications),
            reason="User updated notification preferences"
        )

    async def update_editor_settings(
            self,
            user_id: str,
            editor: DomainEditorSettings
    ) -> DomainUserSettings:
        """Update editor preferences"""
        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(editor=editor),
            reason="User updated editor settings"
        )

    async def update_custom_setting(
            self,
            user_id: str,
            key: str,
            value: Any
    ) -> DomainUserSettings:
        """Update a custom setting"""
        current_settings = await self.get_user_settings(user_id)
        current_settings.custom_settings[key] = value

        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(custom_settings=current_settings.custom_settings),
            reason=f"Custom setting '{key}' updated"
        )

    async def get_settings_history(
            self,
            user_id: str,
            limit: int = 50
    ) -> List[DomainSettingsHistoryEntry]:
        """Get history of settings changes"""
        events = await self._get_settings_events(user_id, limit=limit)

        history: list[DomainSettingsHistoryEntry] = []
        for event in events:
            if event.payload.get("changes"):
                event_timestamp = event.timestamp

                for change in event.payload["changes"]:
                    history.append(
                        DomainSettingsHistoryEntry(
                            timestamp=event_timestamp,
                            event_type=str(event.event_type),
                            field=change["field_path"],
                            old_value=change["old_value"],
                            new_value=change["new_value"],
                            reason=change.get("change_reason"),
                            correlation_id=event.correlation_id,
                        )
                    )

        return history

    async def restore_settings_to_point(
            self,
            user_id: str,
            timestamp: datetime
    ) -> DomainUserSettings:
        """Restore settings to a specific point in time"""
        # Get all events up to the timestamp
        events = await self._get_settings_events(
            user_id,
            until=timestamp
        )

        # Rebuild settings from events
        settings = DomainUserSettings(user_id=user_id)
        for event in events:
            settings = self._apply_event(settings, event)

        # Save as current settings
        await self.repository.create_snapshot(settings)
        self._add_to_cache(user_id, settings)

        # Publish restoration event
        await self.event_service.publish_event(
            event_type=EventType.USER_SETTINGS_UPDATED,
            aggregate_id=f"user_settings_{user_id}",
            payload={
                "user_id": user_id,
                "action": "restored",
                "restored_to": timestamp,
                "reason": f"Settings restored to timestamp {timestamp}"
            },
            user_id=None
        )

        return settings

    async def _get_settings_events(
            self,
            user_id: str,
            since: datetime | None = None,
            until: datetime | None = None,
            limit: int | None = None
    ) -> List[DomainSettingsEvent]:
        """Get settings-related events for a user"""
        event_types = [
            EventType.USER_SETTINGS_UPDATED,
            EventType.USER_THEME_CHANGED,
            EventType.USER_NOTIFICATION_SETTINGS_UPDATED,
            EventType.USER_EDITOR_SETTINGS_UPDATED
        ]

        raw = await self.repository.get_settings_events(
            user_id=user_id,
            event_types=event_types,
            since=since,
            until=until,
            limit=limit
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
        """Apply an event to settings state"""
        # TODO: Refactoring this mess with branching and dict[whatever, whatever]
        payload = event.payload

        # Handle different event types
        if event.event_type == EventType.USER_THEME_CHANGED:
            settings.theme = payload["new_values"]["theme"]

        elif event.event_type == EventType.USER_NOTIFICATION_SETTINGS_UPDATED:
            n = payload["new_values"]["notifications"]
            settings.notifications = DomainNotificationSettings(
                execution_completed=n.get("execution_completed", True),
                execution_failed=n.get("execution_failed", True),
                system_updates=n.get("system_updates", True),
                security_alerts=n.get("security_alerts", True),
                channels=n.get("channels", []),
            )

        elif event.event_type == EventType.USER_EDITOR_SETTINGS_UPDATED:
            e = payload["new_values"]["editor"]
            settings.editor = DomainEditorSettings(
                theme=e.get("theme", settings.editor.theme),
                font_size=e.get("font_size", settings.editor.font_size),
                tab_size=e.get("tab_size", settings.editor.tab_size),
                use_tabs=e.get("use_tabs", settings.editor.use_tabs),
                word_wrap=e.get("word_wrap", settings.editor.word_wrap),
                show_line_numbers=e.get("show_line_numbers", settings.editor.show_line_numbers),
            )

        else:
            # Generic settings update; handle known nested fields explicitly
            for change in payload.get("changes", []):
                field_path = change["field_path"]
                new_value = change["new_value"]
                if "." in field_path:
                    parts = field_path.split(".")
                    top = parts[0]
                    leaf = parts[-1]
                    if top == "editor":
                        setattr(settings.editor, leaf, new_value)
                    elif top == "notifications":
                        setattr(settings.notifications, leaf, new_value)
                    elif top == "custom_settings" and len(parts) == 2:
                        settings.custom_settings[leaf] = new_value
                else:
                    if field_path == "theme":
                        settings.theme = new_value
                    elif field_path == "timezone":
                        settings.timezone = new_value
                    elif field_path == "date_format":
                        settings.date_format = new_value
                    elif field_path == "time_format":
                        settings.time_format = new_value
                    elif field_path == "editor" and isinstance(new_value, dict):
                        e = new_value
                        settings.editor = DomainEditorSettings(
                            theme=e.get("theme", settings.editor.theme),
                            font_size=e.get("font_size", settings.editor.font_size),
                            tab_size=e.get("tab_size", settings.editor.tab_size),
                            use_tabs=e.get("use_tabs", settings.editor.use_tabs),
                            word_wrap=e.get("word_wrap", settings.editor.word_wrap),
                            show_line_numbers=e.get("show_line_numbers", settings.editor.show_line_numbers),
                        )
                    elif field_path == "notifications" and isinstance(new_value, dict):
                        n = new_value
                        settings.notifications = DomainNotificationSettings(
                            execution_completed=n.get("execution_completed",
                                                      settings.notifications.execution_completed),
                            execution_failed=n.get("execution_failed", settings.notifications.execution_failed),
                            system_updates=n.get("system_updates", settings.notifications.system_updates),
                            security_alerts=n.get("security_alerts", settings.notifications.security_alerts),
                            channels=n.get("channels", settings.notifications.channels),
                        )

        settings.updated_at = event.timestamp
        return settings

    def _determine_event_type_from_fields(self, updated_fields: set[str]) -> EventType:
        """Determine event type from top-level updated fields (no brittle path parsing)."""
        field_event_map = {
            "theme": EventType.USER_THEME_CHANGED,
            "notifications": EventType.USER_NOTIFICATION_SETTINGS_UPDATED,
            "editor": EventType.USER_EDITOR_SETTINGS_UPDATED,
        }

        if len(updated_fields) == 1:
            field = next(iter(updated_fields))
            return field_event_map.get(field, EventType.USER_SETTINGS_UPDATED)
        return EventType.USER_SETTINGS_UPDATED

    def invalidate_cache(self, user_id: str) -> None:
        """Invalidate cached settings for a user"""
        if user_id in self._settings_cache:
            del self._settings_cache[user_id]
            logger.debug(
                f"Invalidated cache for user {user_id}",
                extra={"cache_size": len(self._settings_cache)}
            )

    def _get_from_cache(self, user_id: str) -> DomainUserSettings | None:
        """Get settings from cache if valid."""
        if user_id not in self._settings_cache:
            return None

        cached = self._settings_cache[user_id]

        # Check if expired
        if cached.is_expired():
            logger.debug(f"Cache expired for user {user_id}")
            del self._settings_cache[user_id]
            return None

        # Move to end for LRU behavior
        self._settings_cache.move_to_end(user_id)
        return cached.settings

    def _add_to_cache(self, user_id: str, settings: DomainUserSettings) -> None:
        """Add settings to cache with expiry and size management."""
        # Remove expired entries periodically (every 10 additions)
        if len(self._settings_cache) % 10 == 0:
            self._cleanup_expired_cache()

        # Enforce max cache size (LRU eviction)
        while len(self._settings_cache) >= self._max_cache_size:
            # Remove oldest entry (first item in OrderedDict)
            evicted_user_id, _ = self._settings_cache.popitem(last=False)
            logger.debug(
                f"Evicted user {evicted_user_id} from cache (size limit)",
                extra={"cache_size": len(self._settings_cache)}
            )

        # Add new entry with expiry
        expires_at = datetime.now(timezone.utc) + self._cache_ttl
        self._settings_cache[user_id] = CachedSettings(
            settings=settings,
            expires_at=expires_at
        )

        logger.debug(
            f"Cached settings for user {user_id}",
            extra={
                "cache_size": len(self._settings_cache),
                "expires_at": expires_at.isoformat()
            }
        )

    def _cleanup_expired_cache(self) -> None:
        """Remove all expired entries from cache."""
        now = datetime.now(timezone.utc)
        expired_users = [
            user_id for user_id, cached in self._settings_cache.items()
            if cached.expires_at <= now
        ]

        for user_id in expired_users:
            del self._settings_cache[user_id]

        if expired_users:
            logger.debug(
                f"Cleaned up {len(expired_users)} expired cache entries",
                extra={"remaining_cache_size": len(self._settings_cache)}
            )

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring."""
        now = datetime.now(timezone.utc)
        expired_count = sum(
            1 for cached in self._settings_cache.values()
            if cached.expires_at <= now
        )

        return {
            "cache_size": len(self._settings_cache),
            "max_cache_size": self._max_cache_size,
            "expired_entries": expired_count,
            "cache_ttl_seconds": self._cache_ttl.total_seconds()
        }
