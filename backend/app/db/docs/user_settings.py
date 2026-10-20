from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from beanie import Document, Indexed
from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import NotificationChannel, Theme


class NotificationSettings(BaseModel):
    """User notification preferences (embedded document).

    Copied from user_settings.py NotificationSettings.
    """

    model_config = ConfigDict(from_attributes=True)

    execution_completed: bool = True
    execution_failed: bool = True
    system_updates: bool = True
    security_alerts: bool = True
    channels: list[NotificationChannel] = [NotificationChannel.IN_APP]


class EditorSettings(BaseModel):
    """Code editor preferences (embedded document).

    Copied from user_settings.py EditorSettings.
    """

    model_config = ConfigDict(from_attributes=True)

    font_size: int = Field(default=14, ge=8, le=32)
    tab_size: Literal[2, 4, 8] = 4
    use_tabs: bool = False
    word_wrap: bool = True
    show_line_numbers: bool = True


class UserSettingsDocument(Document):
    """Complete user settings model.

    Copied from UserSettings schema.
    """

    user_id: Annotated[str, Indexed(unique=True)]
    theme: Theme = Theme.SYSTEM
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    editor: EditorSettings = Field(default_factory=EditorSettings)
    custom_settings: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "user_settings"
        use_state_management = True
