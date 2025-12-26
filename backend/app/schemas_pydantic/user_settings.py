from datetime import datetime, timezone
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator

from app.domain.enums.common import Theme
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationChannel


class NotificationSettings(BaseModel):
    """User notification preferences"""

    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True
    channels: List[NotificationChannel] = [NotificationChannel.IN_APP]


class EditorSettings(BaseModel):
    """Code editor preferences"""

    theme: str = "auto"
    font_size: int = 14
    tab_size: int = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True

    @field_validator("font_size")
    @classmethod
    def validate_font_size(cls, v: int) -> int:
        if v < 8 or v > 32:
            raise ValueError("Font size must be between 8 and 32")
        return v

    @field_validator("tab_size")
    @classmethod
    def validate_tab_size(cls, v: int) -> int:
        if v not in (2, 4, 8):
            raise ValueError("Tab size must be 2, 4, or 8")
        return v


class UserSettings(BaseModel):
    """Complete user settings model"""

    user_id: str
    theme: Theme = Theme.AUTO
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    editor: EditorSettings = Field(default_factory=EditorSettings)
    custom_settings: Dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserSettingsUpdate(BaseModel):
    """Partial update model for user settings"""

    theme: Theme | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    notifications: NotificationSettings | None = None
    editor: EditorSettings | None = None
    custom_settings: Dict[str, Any] | None = None


class SettingChange(BaseModel):
    """Represents a single setting change for event sourcing"""

    field_path: str  # e.g., "theme", "editor.font_size", "notifications.channels"
    old_value: Any
    new_value: Any
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    change_reason: str | None = None


class ThemeUpdateRequest(BaseModel):
    """Request model for theme update"""

    theme: Theme


class SettingsHistoryEntry(BaseModel):
    """Single entry in settings history"""

    timestamp: datetime
    event_type: EventType
    field: str
    old_value: Any
    new_value: Any
    reason: str | None = None
    correlation_id: str | None = None


class SettingsHistoryResponse(BaseModel):
    """Response model for settings history"""

    history: List[SettingsHistoryEntry]
    total: int


class RestoreSettingsRequest(BaseModel):
    """Request model for restoring settings"""

    timestamp: datetime
    reason: str | None = None


class SettingsEvent(BaseModel):
    """Minimal event model for user settings service consumption."""

    event_type: EventType
    timestamp: datetime
    payload: Dict[str, Any]
    correlation_id: str | None = None
