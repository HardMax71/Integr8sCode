from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums.common import Theme
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationChannel


class DomainNotificationSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True
    channels: list[NotificationChannel] = Field(default_factory=list)


class DomainEditorSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: str = "auto"
    font_size: int = 14
    tab_size: int = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True


class DomainUserSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    theme: Theme = Theme.AUTO
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: DomainNotificationSettings = Field(default_factory=DomainNotificationSettings)
    editor: DomainEditorSettings = Field(default_factory=DomainEditorSettings)
    custom_settings: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DomainUserSettingsUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Theme | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    notifications: DomainNotificationSettings | None = None
    editor: DomainEditorSettings | None = None
    custom_settings: dict[str, Any] | None = None


class DomainSettingChange(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field_path: str
    old_value: Any
    new_value: Any
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    change_reason: str | None = None


class DomainUserSettingsChangedEvent(BaseModel):
    """Well-typed domain event for user settings changes."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

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
    reason: str | None = None
    correlation_id: str | None = None


class DomainSettingsHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    event_type: EventType
    field: str
    old_value: Any
    new_value: Any
    reason: str | None = None
    correlation_id: str | None = None


class CachedSettings(BaseModel):
    """Wrapper for cached user settings with expiration time."""

    model_config = ConfigDict(from_attributes=True)

    settings: DomainUserSettings
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at
