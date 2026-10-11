import dataclasses
from datetime import datetime, timezone
from typing import Any

import structlog

from app.db import UserSettingsRepository
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
from app.events import UnifiedProducer
from app.settings import Settings

# --8<-- [start:settings_fields]
_settings_fields = set(DomainUserSettings.__dataclass_fields__)
# --8<-- [end:settings_fields]


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
    async def get_user_settings(self, user_id: str) -> DomainUserSettings:
        """Rebuild settings from the latest snapshot and the events after it.

        Not cached: each API worker process would keep its own copy, stale after another worker's update.
        """
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

        return settings

    # --8<-- [end:get_user_settings]

    # --8<-- [start:update_user_settings]
    async def update_user_settings(
        self, user_id: str, updates: DomainUserSettingsUpdate, reason: str | None = None
    ) -> DomainUserSettings:
        """Upsert provided fields into current settings and publish a minimal event."""
        current = await self.get_user_settings(user_id)

        changes = {k: v for k, v in dataclasses.asdict(updates).items() if v is not None}
        if not changes:
            return current

        new_settings = self._build_settings(
            {
                **dataclasses.asdict(current),
                **changes,
                "version": (current.version or 0) + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        await self._publish_settings_event(user_id, changes, reason)

        if (await self.repository.count_events_since_snapshot(user_id)) >= 10:
            await self.repository.create_snapshot(new_settings)
        return new_settings

    # --8<-- [end:update_user_settings]

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
        await self._producer.produce(event_to_produce=event, key=f"user_settings_{user_id}")

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
        updated_custom = {**current_settings.custom_settings, key: value}

        return await self.update_user_settings(
            user_id,
            DomainUserSettingsUpdate(custom_settings=updated_custom),
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

    async def restore_settings_to_point(self, user_id: str, timestamp: datetime) -> DomainUserSettings:
        """Restore settings to a specific point in time"""
        events = await self.repository.get_settings_events(user_id, [EventType.USER_SETTINGS_UPDATED], until=timestamp)

        settings = DomainUserSettings(user_id=user_id)
        for event in events:
            settings = self._apply_event(settings, event)

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
        settings = dataclasses.replace(settings, updated_at=restore_event.timestamp)
        await self.repository.create_snapshot(settings)
        await self._producer.produce(event_to_produce=restore_event, key=f"user_settings_{user_id}")

        return settings

    # --8<-- [start:apply_event]
    def _apply_event(self, settings: DomainUserSettings, event: DomainUserSettingsChangedEvent) -> DomainUserSettings:
        """Apply a settings update event via dict merge."""
        event_data = {k: v for k, v in dataclasses.asdict(event).items() if v is not None}
        return self._build_settings({**dataclasses.asdict(settings), **event_data, "updated_at": event.timestamp})

    # --8<-- [end:apply_event]

    @staticmethod
    def _build_settings(data: dict[str, Any]) -> DomainUserSettings:
        filtered = {k: v for k, v in data.items() if k in _settings_fields}
        if isinstance(filtered.get("notifications"), dict):
            filtered["notifications"] = DomainNotificationSettings(**filtered["notifications"])
        if isinstance(filtered.get("editor"), dict):
            filtered["editor"] = DomainEditorSettings(**filtered["editor"])
        return DomainUserSettings(**filtered)
