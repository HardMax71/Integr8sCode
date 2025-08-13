"""User settings and preferences models with event sourcing support"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Theme(StrEnum):
    """Available UI themes"""
    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"




class NotificationChannel(StrEnum):
    """Notification delivery channels"""
    IN_APP = "in_app"


class NotificationSettings(BaseModel):
    """User notification preferences"""
    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True
    channels: List[NotificationChannel] = [NotificationChannel.IN_APP]


class EditorSettings(BaseModel):
    """Code editor preferences"""
    theme: str = "one-dark"
    font_size: int = 14
    tab_size: int = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True
    # These are always on in the editor, not user-configurable
    font_family: str = "Monaco, Consolas, 'Courier New', monospace"
    auto_complete: bool = True
    bracket_matching: bool = True
    highlight_active_line: bool = True
    default_language: str = "python"




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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserSettingsUpdate(BaseModel):
    """Partial update model for user settings"""
    theme: Optional[Theme] = None
    timezone: Optional[str] = None
    date_format: Optional[str] = None
    time_format: Optional[str] = None
    notifications: Optional[NotificationSettings] = None
    editor: Optional[EditorSettings] = None
    custom_settings: Optional[Dict[str, Any]] = None


class SettingChange(BaseModel):
    """Represents a single setting change for event sourcing"""
    field_path: str  # e.g., "theme", "editor.font_size", "notifications.channels"
    old_value: Any
    new_value: Any
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    change_reason: Optional[str] = None


class ThemeUpdateRequest(BaseModel):
    """Request model for theme update"""
    theme: Theme




class SettingsHistoryResponse(BaseModel):
    """Response model for settings history"""
    history: List[dict]
    total: int


class RestoreSettingsRequest(BaseModel):
    """Request model for restoring settings"""
    timestamp: datetime
    reason: Optional[str] = None
