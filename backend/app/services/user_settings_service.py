from datetime import datetime
from typing import Any

import structlog

from app.db import UserSettingsRepository
from app.db.docs import UserSettingsDocument
from app.domain.enums import EventType, Theme
from app.domain.events import EventMetadata, UserSettingsUpdatedEvent
from app.domain.user import (
    DomainEditorSettings,
    DomainNotificationSettings,
    DomainSettingsHistoryEntry,
    DomainUserSettingsChangedEvent,
    UserSettingsChanges,
)
from app.events import UnifiedProducer
from app.settings import Settings


class UserSettingsService:
    def __init__(
        self,
        repository: UserSettingsRepository,
        producer: UnifiedProducer,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self.repository = repository
        self._producer = producer
        self.settings = settings
        self.logger = logger

    # --8<-- [start:get_user_settings]
    async def get_user_settings(self, user_id: str) -> UserSettingsDocument:
        """Rebuild settings from the latest snapshot and the events after it.

        Not cached: each API worker process would keep its own copy, stale after another worker's update.
        """
        snapshot = await self.repository.get_snapshot(user_id)

        event_types = [EventType.USER_SETTINGS_UPDATED]
        if snapshot:
            settings = snapshot
            events = await self.repository.get_settings_events(user_id, event_types, since=snapshot.updated_at)
        else:
            settings = UserSettingsDocument(user_id=user_id)
            events = await self.repository.get_settings_events(user_id, event_types)

        for event in events:
            self._apply_event(settings, event)

        return settings

    # --8<-- [end:get_user_settings]

    # --8<-- [start:update_user_settings]
    async def update_user_settings(
        self, user_id: str, changes: UserSettingsChanges, reason: str | None = None
    ) -> UserSettingsDocument:
        """Publish the changed fields as one event and apply it to the current settings."""
        current = await self.get_user_settings(user_id)
        if not changes:
            return current

        event = await self._publish_settings_event(user_id, changes, reason)
        self._apply_event(
            current,
            DomainUserSettingsChangedEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                user_id=user_id,
                changed_fields=event.changed_fields,
                reason=reason,
                **changes,
            ),
        )
        current.version += 1

        if (await self.repository.count_events_since_snapshot(user_id)) >= 10:
            await self.repository.create_snapshot(current)
        return current

    # --8<-- [end:update_user_settings]

    async def _publish_settings_event(
        self, user_id: str, changes: UserSettingsChanges, reason: str | None
    ) -> UserSettingsUpdatedEvent:
        """Publish a settings update event that carries the changed fields as its extra fields."""
        event = UserSettingsUpdatedEvent.model_validate(
            {
                "aggregate_id": f"user_settings_{user_id}",
                "user_id": user_id,
                "changed_fields": list(changes.keys()),
                "reason": reason,
                "metadata": EventMetadata(
                    service_name="integr8scode-user-settings",
                    service_version="1.0.0",
                    user_id=user_id,
                ),
                **changes,
            }
        )
        await self._producer.produce(event_to_produce=event, key=f"user_settings_{user_id}")
        return event

    async def update_theme(self, user_id: str, theme: Theme) -> UserSettingsDocument:
        """Update user's theme preference"""
        return await self.update_user_settings(user_id, UserSettingsChanges(theme=theme), reason="User changed theme")

    async def update_notification_settings(
        self, user_id: str, notifications: DomainNotificationSettings
    ) -> UserSettingsDocument:
        """Update notification preferences"""
        return await self.update_user_settings(
            user_id,
            UserSettingsChanges(notifications=notifications),
            reason="User updated notification preferences",
        )

    async def update_editor_settings(self, user_id: str, editor: DomainEditorSettings) -> UserSettingsDocument:
        """Update editor preferences"""
        return await self.update_user_settings(
            user_id, UserSettingsChanges(editor=editor), reason="User updated editor settings"
        )

    async def update_custom_setting(self, user_id: str, key: str, value: Any) -> UserSettingsDocument:
        """Update a custom setting"""
        current_settings = await self.get_user_settings(user_id)
        updated_custom = {**current_settings.custom_settings, key: value}

        return await self.update_user_settings(
            user_id,
            UserSettingsChanges(custom_settings=updated_custom),
            reason=f"Custom setting '{key}' updated",
        )

    # --8<-- [start:get_settings_history]
    async def get_settings_history(self, user_id: str, limit: int = 50) -> list[DomainSettingsHistoryEntry]:
        """Get history from changed fields recorded in the newest events, newest first."""
        events = await self.repository.get_settings_events(
            user_id, [EventType.USER_SETTINGS_UPDATED], limit=limit, newest_first=True
        )
        history: list[DomainSettingsHistoryEntry] = []
        for event in events:
            for fld in event.changed_fields:
                history.append(
                    DomainSettingsHistoryEntry(
                        timestamp=event.timestamp,
                        event_type=event.event_type,
                        field=f"/{fld}",
                        old_value=None,
                        new_value=getattr(event, fld, None),
                        reason=event.reason,
                    )
                )
        return history

    # --8<-- [end:get_settings_history]

    async def restore_settings_to_point(self, user_id: str, timestamp: datetime) -> UserSettingsDocument:
        """Restore settings to a specific point in time"""
        events = await self.repository.get_settings_events(user_id, [EventType.USER_SETTINGS_UPDATED], until=timestamp)

        settings = UserSettingsDocument(user_id=user_id)
        for event in events:
            self._apply_event(settings, event)

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
        # Rebuilds replay events after updated_at, so the snapshot carries the restore time
        settings.updated_at = restore_event.timestamp
        await self.repository.create_snapshot(settings)
        await self._producer.produce(event_to_produce=restore_event, key=f"user_settings_{user_id}")

        return settings

    # --8<-- [start:apply_event]
    def _apply_event(self, settings: UserSettingsDocument, event: DomainUserSettingsChangedEvent) -> None:
        """Set the fields a settings update event carries."""
        if event.theme is not None:
            settings.theme = event.theme
        if event.timezone is not None:
            settings.timezone = event.timezone
        if event.date_format is not None:
            settings.date_format = event.date_format
        if event.time_format is not None:
            settings.time_format = event.time_format
        if event.notifications is not None:
            settings.notifications = event.notifications
        if event.editor is not None:
            settings.editor = event.editor
        if event.custom_settings is not None:
            settings.custom_settings = event.custom_settings
        settings.updated_at = event.timestamp

    # --8<-- [end:apply_event]
