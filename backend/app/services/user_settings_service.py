from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.logging import logger
from app.schemas_avro.event_schemas import EventType
from app.schemas_pydantic.user import User
from app.schemas_pydantic.user_settings import (
    EditorSettings,
    NotificationChannel,
    NotificationSettings,
    SettingChange,
    Theme,
    UserSettings,
    UserSettingsUpdate,
)
from app.services.kafka_event_service import KafkaEventService


class UserSettingsService:
    """Service for managing user settings with event sourcing"""

    def __init__(self, database: AsyncIOMotorDatabase, event_service: KafkaEventService) -> None:
        self._db: AsyncIOMotorDatabase[Any] = database
        self.event_service = event_service
        self._settings_cache: Dict[str, UserSettings] = {}

    @property
    def db(self) -> AsyncIOMotorDatabase[Any]:
        """Get database with null check"""
        if self._db is None:
            raise RuntimeError("Database not initialized")
        return self._db

    async def initialize(self) -> None:
        """Initialize collections and indexes"""
        # Create indexes for settings snapshots
        await self.db.user_settings_snapshots.create_indexes([
            IndexModel([("user_id", ASCENDING)], unique=True),
            IndexModel([("updated_at", DESCENDING)]),
        ])

        # Create indexes for settings events
        await self.db.events.create_indexes([
            IndexModel([("event_type", ASCENDING), ("aggregate_id", ASCENDING)]),
            IndexModel([("aggregate_id", ASCENDING), ("timestamp", ASCENDING)]),
        ])

        logger.info("User settings service initialized")

    async def get_user_settings(self, user_id: str, use_cache: bool = True) -> UserSettings:
        """Get user settings by rebuilding from events or snapshot"""
        # Check cache first
        if use_cache and user_id in self._settings_cache:
            return self._settings_cache[user_id]

        # Try to get latest snapshot
        snapshot = await self.db.user_settings_snapshots.find_one({"user_id": user_id})

        if snapshot:
            settings = UserSettings(**snapshot)
            # Get events since snapshot
            events = await self._get_settings_events(user_id, since=settings.updated_at)
        else:
            # No snapshot, rebuild from all events
            settings = UserSettings(user_id=user_id)
            events = await self._get_settings_events(user_id)

        # Apply events to rebuild current state
        for event in events:
            settings = self._apply_event(settings, event)

        # Cache the settings
        self._settings_cache[user_id] = settings

        return settings

    async def update_user_settings(
            self,
            user: User,
            updates: UserSettingsUpdate,
            reason: Optional[str] = None
    ) -> UserSettings:
        """Update user settings and publish events"""
        # Get current settings
        current_settings = await self.get_user_settings(str(user.user_id))

        # Track changes
        changes = []
        update_dict = updates.model_dump(exclude_unset=True)

        # Apply updates and record changes
        for field, value in update_dict.items():
            if value is not None:
                old_value = getattr(current_settings, field)
                if old_value != value:
                    changes.append(SettingChange(
                        field_path=field,
                        old_value=old_value,
                        new_value=value,
                        change_reason=reason
                    ))
                    setattr(current_settings, field, value)

        if not changes:
            return current_settings  # No changes

        # Update timestamp
        current_settings.updated_at = datetime.now(timezone.utc)

        # Publish event based on what changed
        event_type = self._determine_event_type(changes)

        await self.event_service.publish_event(
            event_type=event_type,
            aggregate_id=f"user_settings_{user.user_id}",
            payload={
                "user_id": str(user.user_id),
                "changes": [change.dict() for change in changes],
                "reason": reason,
                "new_values": update_dict
            },
            user=user
        )

        # Update cache
        self._settings_cache[str(user.user_id)] = current_settings

        # Create snapshot if enough changes accumulated
        event_count = await self._count_events_since_snapshot(str(user.user_id))
        if event_count >= 10:  # Snapshot every 10 events
            await self._create_snapshot(current_settings)

        return current_settings

    async def update_theme(self, user: User, theme: Theme) -> UserSettings:
        """Update user's theme preference"""
        return await self.update_user_settings(
            user,
            UserSettingsUpdate(theme=theme),
            reason="User changed theme"
        )

    async def update_notification_settings(
            self,
            user: User,
            notifications: NotificationSettings
    ) -> UserSettings:
        """Update notification preferences"""
        return await self.update_user_settings(
            user,
            UserSettingsUpdate(notifications=notifications),
            reason="User updated notification preferences"
        )

    async def update_editor_settings(
            self,
            user: User,
            editor: EditorSettings
    ) -> UserSettings:
        """Update editor preferences"""
        return await self.update_user_settings(
            user,
            UserSettingsUpdate(editor=editor),
            reason="User updated editor settings"
        )

    async def update_custom_setting(
            self,
            user: User,
            key: str,
            value: Any
    ) -> UserSettings:
        """Update a custom setting"""
        current_settings = await self.get_user_settings(str(user.user_id))
        current_settings.custom_settings[key] = value

        return await self.update_user_settings(
            user,
            UserSettingsUpdate(custom_settings=current_settings.custom_settings),
            reason=f"Custom setting '{key}' updated"
        )

    async def get_settings_history(
            self,
            user_id: str,
            limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get history of settings changes"""
        events = await self._get_settings_events(user_id, limit=limit)

        history = []
        for event in events:
            if event.get("payload", {}).get("changes"):
                for change in event["payload"]["changes"]:
                    history.append({
                        "timestamp": event["timestamp"],
                        "event_type": event["event_type"],
                        "field": change["field_path"],
                        "old_value": change["old_value"],
                        "new_value": change["new_value"],
                        "reason": change.get("change_reason"),
                        "correlation_id": event.get("correlation_id")
                    })

        return history

    async def restore_settings_to_point(
            self,
            user: User,
            timestamp: datetime
    ) -> UserSettings:
        """Restore settings to a specific point in time"""
        # Get all events up to the timestamp
        events = await self._get_settings_events(
            str(user.user_id),
            until=timestamp
        )

        # Rebuild settings from events
        settings = UserSettings(user_id=str(user.user_id))
        for event in events:
            settings = self._apply_event(settings, event)

        # Save as current settings
        await self._create_snapshot(settings)
        self._settings_cache[str(user.user_id)] = settings

        # Publish restoration event
        await self.event_service.publish_event(
            event_type=EventType.USER_SETTINGS_UPDATED,
            aggregate_id=f"user_settings_{user.user_id}",
            payload={
                "user_id": str(user.user_id),
                "action": "restored",
                "restored_to": timestamp.isoformat(),
                "reason": f"Settings restored to {timestamp}"
            },
            user=user
        )

        return settings

    async def migrate_legacy_settings(self, user_id: str, legacy_settings: Dict[str, Any]) -> UserSettings:
        """Migrate legacy settings to event-sourced model"""
        # Map notification settings
        notifications = NotificationSettings()
        if "notifications" in legacy_settings:
            legacy_notif = legacy_settings["notifications"]
            notifications.execution_completed = legacy_notif.get("execution_completed", True)
            notifications.execution_failed = legacy_notif.get("execution_failed", True)
            notifications.system_updates = legacy_notif.get("system_updates", True)
            notifications.security_alerts = legacy_notif.get("security_alerts", True)

            # Map notification channels
            if "channels" in legacy_notif:
                channels = []
                for channel in legacy_notif["channels"]:
                    try:
                        channels.append(NotificationChannel(channel))
                    except ValueError:
                        logger.warning(f"Unknown notification channel in legacy settings: {channel}")
                if channels:
                    notifications.channels = channels

            # Email-related settings removed
            pass

        # Map editor settings
        editor = EditorSettings()
        if "editor" in legacy_settings:
            legacy_editor = legacy_settings["editor"]
            editor.theme = legacy_editor.get("theme", "one-dark")
            editor.font_size = legacy_editor.get("font_size", 14)
            editor.font_family = legacy_editor.get("font_family", editor.font_family)
            editor.tab_size = legacy_editor.get("tab_size", 4)
            editor.use_tabs = legacy_editor.get("use_tabs", False)
            editor.word_wrap = legacy_editor.get("word_wrap", True)
            editor.show_line_numbers = legacy_editor.get("show_line_numbers", True)
            # vim_mode removed, auto_complete is always on
            editor.auto_complete = True
            editor.bracket_matching = legacy_editor.get("bracket_matching", True)
            editor.highlight_active_line = legacy_editor.get("highlight_active_line", True)
            editor.default_language = legacy_editor.get("default_language", "python")

        # User preferences removed - execution settings defined at infra level

        # Map custom settings
        custom_settings = {}
        # Collect any fields not mapped to standard settings
        standard_fields = {
            "theme", "language", "timezone", "date_format", "time_format",
            "notifications", "editor", "preferences", "user_id", "version",
            "created_at", "updated_at"
        }
        for key, value in legacy_settings.items():
            if key not in standard_fields:
                custom_settings[key] = value

        # Create initial settings from legacy data
        settings = UserSettings(
            user_id=user_id,
            theme=Theme(legacy_settings.get("theme", "auto")),
            timezone=legacy_settings.get("timezone", "UTC"),
            date_format=legacy_settings.get("date_format", "YYYY-MM-DD"),
            time_format=legacy_settings.get("time_format", "24h"),
            notifications=notifications,
            editor=editor,
            custom_settings=custom_settings
        )

        # Create initial event
        await self.event_service.publish_event(
            event_type=EventType.USER_SETTINGS_UPDATED,
            aggregate_id=f"user_settings_{user_id}",
            payload={
                "user_id": user_id,
                "action": "migrated",
                "migrated_from": "legacy",
                "initial_settings": settings.model_dump()
            }
        )

        # Create snapshot
        await self._create_snapshot(settings)

        return settings

    async def migrate_flat_legacy_settings(self, user_id: str, legacy_settings: Dict[str, Any]) -> UserSettings:
        """Migrate flat legacy settings (non-nested structure) to event-sourced model"""
        # Reorganize flat settings into nested structure
        organized_settings: Dict[str, Any] = {
            "theme": legacy_settings.get("theme"),
            "language": legacy_settings.get("language"),
            "timezone": legacy_settings.get("timezone"),
            "date_format": legacy_settings.get("date_format"),
            "time_format": legacy_settings.get("time_format"),
            "notifications": {},
            "editor": {},
            "preferences": {}
        }

        # Map notification-related fields
        notification_fields = {
            "notif_execution_completed": "execution_completed",
            "notif_execution_failed": "execution_failed",
            "notif_system_updates": "system_updates",
            "notif_security_alerts": "security_alerts",
            "notif_channels": "channels",
            "notif_email_frequency": "email_frequency",
            "notif_quiet_hours_start": "quiet_hours_start",
            "notif_quiet_hours_end": "quiet_hours_end"
        }

        for legacy_key, new_key in notification_fields.items():
            if legacy_key in legacy_settings:
                if isinstance(organized_settings["notifications"], dict):
                    organized_settings["notifications"][new_key] = legacy_settings[legacy_key]

        # Map editor-related fields
        editor_fields = {
            "editor_theme": "theme",
            "editor_font_size": "font_size",
            "editor_font_family": "font_family",
            "editor_tab_size": "tab_size",
            "editor_use_tabs": "use_tabs",
            "editor_word_wrap": "word_wrap",
            "editor_show_line_numbers": "show_line_numbers",
            "editor_show_minimap": "show_minimap",
            "editor_vim_mode": "vim_mode",
            "editor_auto_complete": "auto_complete",
            "editor_bracket_matching": "bracket_matching",
            "editor_highlight_active_line": "highlight_active_line",
            "editor_default_language": "default_language"
        }

        for legacy_key, new_key in editor_fields.items():
            if legacy_key in legacy_settings:
                if isinstance(organized_settings["editor"], dict):
                    organized_settings["editor"][new_key] = legacy_settings[legacy_key]

        # Map preference-related fields
        preference_fields = {
            "pref_default_execution_timeout": "default_execution_timeout",
            "pref_default_memory_limit": "default_memory_limit",
            "pref_default_cpu_limit": "default_cpu_limit",
            "pref_show_execution_timer": "show_execution_timer",
            "pref_show_resource_usage": "show_resource_usage",
            "pref_auto_run_on_load": "auto_run_on_load",
            "pref_save_output_history": "save_output_history",
            "pref_output_history_limit": "output_history_limit",
            "pref_confirm_before_run": "confirm_before_run",
            "pref_show_execution_cost": "show_execution_cost"
        }

        for legacy_key, new_key in preference_fields.items():
            if legacy_key in legacy_settings:
                if isinstance(organized_settings["preferences"], dict):
                    organized_settings["preferences"][new_key] = legacy_settings[legacy_key]

        # Use the existing migration method with organized settings
        return await self.migrate_legacy_settings(user_id, organized_settings)

    async def _get_settings_events(
            self,
            user_id: str,
            since: Optional[datetime] = None,
            until: Optional[datetime] = None,
            limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get settings-related events for a user"""
        query = {
            "aggregate_id": f"user_settings_{user_id}",
            "event_type": {
                "$in": [
                    EventType.USER_SETTINGS_UPDATED,
                    EventType.USER_PREFERENCES_UPDATED,
                    EventType.USER_THEME_CHANGED,
                    EventType.USER_LANGUAGE_CHANGED,
                    EventType.USER_NOTIFICATION_SETTINGS_UPDATED,
                    EventType.USER_EDITOR_SETTINGS_UPDATED
                ]
            }
        }

        if since or until:
            timestamp_query: Dict[str, Any] = {}
            if since:
                timestamp_query["$gt"] = since
            if until:
                timestamp_query["$lte"] = until
            query["timestamp"] = timestamp_query

        cursor = self.db.events.find(query).sort("timestamp", ASCENDING)

        if limit:
            cursor = cursor.limit(limit)

        return await cursor.to_list(None)

    def _apply_event(self, settings: UserSettings, event: Dict[str, Any]) -> UserSettings:
        """Apply an event to settings state"""
        payload = event.get("payload", {})

        # Handle different event types
        if event["event_type"] == EventType.USER_THEME_CHANGED:
            settings.theme = Theme(payload["new_values"]["theme"])

        elif event["event_type"] == EventType.USER_LANGUAGE_CHANGED:
            # Language removed - app is English only
            pass

        elif event["event_type"] == EventType.USER_NOTIFICATION_SETTINGS_UPDATED:
            settings.notifications = NotificationSettings(**payload["new_values"]["notifications"])

        elif event["event_type"] == EventType.USER_EDITOR_SETTINGS_UPDATED:
            settings.editor = EditorSettings(**payload["new_values"]["editor"])

        elif event["event_type"] == EventType.USER_PREFERENCES_UPDATED:
            # User preferences removed - execution settings defined at infra level
            pass

        else:
            # Generic settings update
            for change in payload.get("changes", []):
                field_path = change["field_path"]
                new_value = change["new_value"]

                # Handle nested fields
                if "." in field_path:
                    parts = field_path.split(".")
                    obj = settings
                    for part in parts[:-1]:
                        obj = getattr(obj, part)
                    setattr(obj, parts[-1], new_value)
                else:
                    setattr(settings, field_path, new_value)

        settings.updated_at = event["timestamp"]
        return settings

    def _determine_event_type(self, changes: List[SettingChange]) -> str:
        """Determine the appropriate event type based on changes"""
        field_paths = [change.field_path for change in changes]

        if any("theme" in path for path in field_paths):
            return EventType.USER_THEME_CHANGED
        elif any("language" in path for path in field_paths):
            return EventType.USER_LANGUAGE_CHANGED
        elif any("notifications" in path for path in field_paths):
            return EventType.USER_NOTIFICATION_SETTINGS_UPDATED
        elif any("editor" in path for path in field_paths):
            return EventType.USER_EDITOR_SETTINGS_UPDATED
        elif any("preferences" in path for path in field_paths):
            return EventType.USER_PREFERENCES_UPDATED
        else:
            return EventType.USER_SETTINGS_UPDATED

    async def _create_snapshot(self, settings: UserSettings) -> None:
        """Create a snapshot of current settings state"""
        await self.db.user_settings_snapshots.replace_one(
            {"user_id": settings.user_id},
            settings.model_dump(),
            upsert=True
        )
        logger.info(f"Created settings snapshot for user {settings.user_id}")

    async def _count_events_since_snapshot(self, user_id: str) -> int:
        """Count events since last snapshot"""
        snapshot = await self.db.user_settings_snapshots.find_one({"user_id": user_id})

        if not snapshot:
            return await self.db.events.count_documents({
                "aggregate_id": f"user_settings_{user_id}"
            })

        return await self.db.events.count_documents({
            "aggregate_id": f"user_settings_{user_id}",
            "timestamp": {"$gt": snapshot["updated_at"]}
        })

    def invalidate_cache(self, user_id: str) -> None:
        """Invalidate cached settings for a user"""
        if user_id in self._settings_cache:
            del self._settings_cache[user_id]
