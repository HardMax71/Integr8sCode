from dataclasses import dataclass

from app.core.utils import StringEnum


class AuditAction(StringEnum):
    """Audit log action types."""

    SYSTEM_SETTINGS_UPDATED = "system_settings_updated"
    SYSTEM_SETTINGS_RESET = "system_settings_reset"


@dataclass
class SystemSettings:
    """Flat system-wide settings for execution and security."""

    max_timeout_seconds: int = 300
    memory_limit: str = "512Mi"
    cpu_limit: str = "2000m"
    max_concurrent_executions: int = 10
    max_executions_per_user: int = 100

    password_min_length: int = 8
    session_timeout_minutes: int = 60
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15
