from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.domain.enums import EventType, NotificationChannel, Theme


@dataclass
class DomainNotificationSettings:
    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True
    channels: list[NotificationChannel] = field(default_factory=lambda: [NotificationChannel.IN_APP])


@dataclass
class DomainEditorSettings:
    font_size: int = 14
    tab_size: int = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True


@dataclass
class DomainUserSettings:
    user_id: str
    theme: Theme = Theme.AUTO
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: DomainNotificationSettings = field(default_factory=DomainNotificationSettings)
    editor: DomainEditorSettings = field(default_factory=DomainEditorSettings)
    custom_settings: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DomainUserSettingsUpdate:
    theme: Theme | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    notifications: DomainNotificationSettings | None = None
    editor: DomainEditorSettings | None = None
    custom_settings: dict[str, Any] | None = None


@dataclass
class DomainUserSettingsChangedEvent:
    """Well-typed domain event for user settings changes."""

    event_id: str
    event_type: EventType
    timestamp: datetime
    user_id: str
    changed_fields: list[str]
    theme: Theme | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    notifications: DomainNotificationSettings | None = None
    editor: DomainEditorSettings | None = None
    custom_settings: dict[str, Any] | None = None
    reason: str | None = None


@dataclass
class DomainSettingsHistoryEntry:
    """Domain model for a single settings history entry."""

    timestamp: datetime
    event_type: EventType
    field: str
    old_value: Any
    new_value: Any
    reason: str | None = None


@dataclass
class CachedSettings:
    """Wrapper for cached user settings with expiration time."""

    settings: DomainUserSettings
    expires_at: datetime
