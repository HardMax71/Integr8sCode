from pydantic import BaseModel, ConfigDict, Field

from app.core.utils import StringEnum

K8S_MEMORY_PATTERN = r"^[1-9]\d*(Ki|Mi|Gi)$"
K8S_CPU_PATTERN = r"^[1-9]\d*m$"


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


class SystemSettings(BaseModel):
    """Flat system-wide settings — execution, security, and monitoring."""

    model_config = ConfigDict(from_attributes=True, extra="ignore", use_enum_values=True)

    max_timeout_seconds: int = Field(300, ge=1, le=3600)
    memory_limit: str = Field("512Mi", pattern=K8S_MEMORY_PATTERN)
    cpu_limit: str = Field("2000m", pattern=K8S_CPU_PATTERN)
    max_concurrent_executions: int = Field(10, ge=1, le=100)

    password_min_length: int = Field(8, ge=8, le=32)
    session_timeout_minutes: int = Field(60, ge=5, le=1440)
    max_login_attempts: int = Field(5, ge=3, le=10)
    lockout_duration_minutes: int = Field(15, ge=5, le=60)

    metrics_retention_days: int = Field(30, ge=7, le=90)
    log_level: LogLevel = LogLevel.INFO
    enable_tracing: bool = True
    sampling_rate: float = Field(0.1, ge=0.0, le=1.0)
