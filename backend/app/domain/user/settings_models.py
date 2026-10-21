from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from app.domain.enums import EventType, Theme


@dataclass
class DomainNotificationSettings:
    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True


@dataclass
class DomainEditorSettings:
    font_size: int = 14
    tab_size: int = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True


class UserSettingsChanges(TypedDict, total=False):
    """Fields an update sets on a user's settings; a missing key keeps the current value."""

    theme: Theme
    timezone: str
    date_format: str
    time_format: str
    notifications: DomainNotificationSettings
    editor: DomainEditorSettings
    custom_settings: dict[str, Any]


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
