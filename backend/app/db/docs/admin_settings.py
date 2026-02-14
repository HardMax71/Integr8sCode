from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import ConfigDict, Field

from app.domain.admin import AuditAction
from app.schemas_pydantic.admin_settings import SystemSettingsSchema


class SystemSettingsDocument(Document):
    settings_id: str = "global"
    config: SystemSettingsSchema = Field(default_factory=SystemSettingsSchema)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    class Settings:
        name = "system_settings"
        use_state_management = True


class AuditLogDocument(Document):
    audit_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    action: AuditAction
    user_id: Indexed(str)  # type: ignore[valid-type]
    timestamp: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "audit_log"
        use_state_management = True
