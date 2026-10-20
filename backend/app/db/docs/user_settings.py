import dataclasses
from datetime import datetime, timezone
from typing import Annotated, Any

from beanie import Document, Indexed
from pydantic import ConfigDict, Field

from app.domain.enums import Theme
from app.domain.user import DomainEditorSettings, DomainNotificationSettings


class UserSettingsDocument(Document):
    """A user's settings snapshot; the settings events after updated_at apply on top of it."""

    user_id: Annotated[str, Indexed(unique=True)]
    theme: Theme = Theme.SYSTEM
    timezone: str = "UTC"
    date_format: str = "YYYY-MM-DD"
    time_format: str = "24h"
    notifications: DomainNotificationSettings = Field(default_factory=DomainNotificationSettings)
    editor: DomainEditorSettings = Field(default_factory=DomainEditorSettings)
    custom_settings: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "user_settings"
        use_state_management = True
        bson_encoders = {DomainNotificationSettings: dataclasses.asdict, DomainEditorSettings: dataclasses.asdict}
