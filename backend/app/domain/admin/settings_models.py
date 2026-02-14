from dataclasses import dataclass

from app.core.utils import StringEnum


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
class SystemSettings:
    """Flat system-wide settings — execution, security, and monitoring."""

    max_timeout_seconds: int = 300
    memory_limit: str = "512Mi"
    cpu_limit: str = "2000m"
    max_concurrent_executions: int = 10

    password_min_length: int = 8
    session_timeout_minutes: int = 60
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15

    metrics_retention_days: int = 30
    log_level: LogLevel = LogLevel.INFO
    enable_tracing: bool = True
    sampling_rate: float = 0.1
