from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, ConfigDict, Field

from app.domain.admin import AuditAction, LogLevel


class ExecutionLimitsConfig(BaseModel):
    max_timeout_seconds: int = 300
    max_memory_mb: int = 512
    max_cpu_cores: int = 2
    max_concurrent_executions: int = 10


class SecuritySettingsConfig(BaseModel):
    password_min_length: int = 8
    session_timeout_minutes: int = 60
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15


class MonitoringSettingsConfig(BaseModel):
    metrics_retention_days: int = 30
    log_level: LogLevel = LogLevel.INFO
    enable_tracing: bool = True
    sampling_rate: float = 0.1


class SystemSettingsDocument(Document):
    settings_id: str = "global"
    execution_limits: ExecutionLimitsConfig = Field(default_factory=ExecutionLimitsConfig)
    security_settings: SecuritySettingsConfig = Field(default_factory=SecuritySettingsConfig)
    monitoring_settings: MonitoringSettingsConfig = Field(default_factory=MonitoringSettingsConfig)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "system_settings"
        use_state_management = True


class AuditLogDocument(Document):
    audit_id: Indexed(str, unique=True) = Field(default_factory=lambda: str(uuid4()))  # type: ignore[valid-type]
    action: AuditAction
    user_id: Indexed(str)  # type: ignore[valid-type]
    username: str
    timestamp: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))  # type: ignore[valid-type]
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""

    model_config = ConfigDict(from_attributes=True)

    class Settings:
        name = "audit_log"
        use_state_management = True
