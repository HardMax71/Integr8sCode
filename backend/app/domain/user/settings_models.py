from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.enums.common import Theme
from app.domain.enums.events import EventType


@dataclass
class DomainNotificationSettings:
    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True
    channels: List[Any] = field(default_factory=list)


@dataclass
class DomainEditorSettings:
    theme: str = "one-dark"
    font_size: int = 14
    tab_size: int = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True
    # fixed, non-configurable editor attributes are omitted from domain
    # as they are UI concerns


@dataclass
class DomainUserSettings:
    user_id: str
    theme: Theme = Theme.AUTO
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: DomainNotificationSettings = field(default_factory=DomainNotificationSettings)
    editor: DomainEditorSettings = field(default_factory=DomainEditorSettings)
    custom_settings: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DomainUserSettingsUpdate:
    theme: Optional[Theme] = None
    timezone: Optional[str] = None
    date_format: Optional[str] = None
    time_format: Optional[str] = None
    notifications: Optional[DomainNotificationSettings] = None
    editor: Optional[DomainEditorSettings] = None
    custom_settings: Optional[Dict[str, Any]] = None

    def to_update_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.theme is not None:
            out["theme"] = self.theme
        if self.timezone is not None:
            out["timezone"] = self.timezone
        if self.date_format is not None:
            out["date_format"] = self.date_format
        if self.time_format is not None:
            out["time_format"] = self.time_format
        if self.notifications is not None:
            out["notifications"] = self.notifications
        if self.editor is not None:
            out["editor"] = self.editor
        if self.custom_settings is not None:
            out["custom_settings"] = self.custom_settings
        return out


@dataclass
class DomainSettingChange:
    field_path: str
    old_value: Any
    new_value: Any
    changed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    change_reason: Optional[str] = None


@dataclass
class DomainSettingsEvent:
    event_type: EventType
    timestamp: datetime
    payload: Dict[str, Any]
    correlation_id: Optional[str] = None


@dataclass
class DomainSettingsHistoryEntry:
    timestamp: datetime
    event_type: str
    field: str
    old_value: Any
    new_value: Any
    reason: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class CachedSettings:
    """Wrapper for cached user settings with expiration time."""
    settings: DomainUserSettings
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at
