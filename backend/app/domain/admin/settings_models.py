import re
from dataclasses import dataclass
from typing import Any

from app.core.utils import StringEnum

K8S_MEMORY_PATTERN = re.compile(r"^[1-9]\d*(Ki|Mi|Gi)$")
K8S_CPU_PATTERN = re.compile(r"^[1-9]\d*m$")

_RANGE_RULES: dict[str, tuple[int | float, int | float]] = {
    "max_timeout_seconds": (1, 3600),
    "max_concurrent_executions": (1, 100),
    "password_min_length": (8, 32),
    "session_timeout_minutes": (5, 1440),
    "max_login_attempts": (3, 10),
    "lockout_duration_minutes": (5, 60),
    "metrics_retention_days": (7, 90),
    "sampling_rate": (0.0, 1.0),
}


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

    def __post_init__(self) -> None:
        for name, (lo, hi) in _RANGE_RULES.items():
            val = getattr(self, name)
            if not (lo <= val <= hi):
                raise ValueError(f"{name} must be between {lo} and {hi}")

        if not K8S_MEMORY_PATTERN.match(self.memory_limit):
            raise ValueError(f"memory_limit must match K8s resource format, got '{self.memory_limit}'")
        if not K8S_CPU_PATTERN.match(self.cpu_limit):
            raise ValueError(f"cpu_limit must match K8s millicore format, got '{self.cpu_limit}'")

        raw: Any = self.log_level
        if not isinstance(raw, LogLevel):
            self.log_level = LogLevel(raw)
