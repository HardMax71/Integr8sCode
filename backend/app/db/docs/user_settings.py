from datetime import datetime, timezone
from typing import Any

from beanie import Document, Indexed
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums.common import Theme
from app.domain.enums.notification import NotificationChannel


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


class UserSettingsDocument(Document):
    """Complete user settings model.

    Copied from UserSettings schema.
    """

    user_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    theme: Theme = Theme.AUTO
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


class UserSettingsSnapshotDocument(Document):
    """Snapshot of user settings for history/restore.

    Based on UserSettings with additional snapshot metadata.
    """

    user_id: Indexed(str)  # type: ignore[valid-type]
    snapshot_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]

    # Full settings snapshot
    theme: Theme = Theme.AUTO
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    editor: EditorSettings = Field(default_factory=EditorSettings)
    custom_settings: dict[str, Any] = Field(default_factory=dict)
    version: int = 1

    # Snapshot metadata
    reason: str | None = None
    correlation_id: str | None = None

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "user_settings_snapshots"
        use_state_management = True
