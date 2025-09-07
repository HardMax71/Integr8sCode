from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.utils import StringEnum


class SettingsFields(StringEnum):
    """Database field names for settings collection."""
    ID = "_id"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    UPDATED_BY = "updated_by"
    EXECUTION_LIMITS = "execution_limits"
    SECURITY_SETTINGS = "security_settings"
    MONITORING_SETTINGS = "monitoring_settings"


class AuditLogFields(StringEnum):
    """Database field names for audit log collection."""
    ACTION = "action"
    USER_ID = "user_id"
    USERNAME = "username"
    TIMESTAMP = "timestamp"
    CHANGES = "changes"


class AuditAction(StringEnum):
    """Audit log action types."""
    SYSTEM_SETTINGS_UPDATED = "system_settings_updated"
    SYSTEM_SETTINGS_RESET = "system_settings_reset"


class LogLevel(StringEnum):
    """Log level options."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class ExecutionLimits:
    max_timeout_seconds: int = 300
    max_memory_mb: int = 512
    max_cpu_cores: int = 2
    max_concurrent_executions: int = 10


@dataclass
class SecuritySettings:
    password_min_length: int = 8
    session_timeout_minutes: int = 60
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15


@dataclass
class MonitoringSettings:
    metrics_retention_days: int = 30
    log_level: LogLevel = LogLevel.INFO
    enable_tracing: bool = True
    sampling_rate: float = 0.1


@dataclass
class SystemSettings:
    """Complete system settings configuration."""
    execution_limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    security_settings: SecuritySettings = field(default_factory=SecuritySettings)
    monitoring_settings: MonitoringSettings = field(default_factory=MonitoringSettings)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AuditLogEntry:
    action: AuditAction
    user_id: str
    username: str
    timestamp: datetime
    changes: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
