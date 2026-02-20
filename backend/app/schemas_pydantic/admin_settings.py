import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.admin.settings_models import LogLevel

_MEMORY_PATTERN = re.compile(r"^\d+(Mi|Gi|Ki)$")
_CPU_PATTERN = re.compile(r"^\d+m$")


class SystemSettingsSchema(BaseModel):
    """API schema for system settings with validation."""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    max_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    memory_limit: str = "512Mi"
    cpu_limit: str = "2000m"
    max_concurrent_executions: int = Field(default=10, ge=1, le=100)

    password_min_length: int = Field(default=8, ge=8, le=32)
    session_timeout_minutes: int = Field(default=60, ge=5, le=1440)
    max_login_attempts: int = Field(default=5, ge=3, le=10)
    lockout_duration_minutes: int = Field(default=15, ge=5, le=60)

    metrics_retention_days: int = Field(default=30, ge=7, le=90)
    log_level: LogLevel = LogLevel.INFO
    enable_tracing: bool = True
    sampling_rate: float = Field(default=0.1, ge=0.0, le=1.0)

    @field_validator("memory_limit")
    @classmethod
    def validate_memory_limit(cls, v: str) -> str:
        if not _MEMORY_PATTERN.match(v):
            msg = "memory_limit must match K8s pattern (e.g. 512Mi, 1Gi)"
            raise ValueError(msg)
        return v

    @field_validator("cpu_limit")
    @classmethod
    def validate_cpu_limit(cls, v: str) -> str:
        if not _CPU_PATTERN.match(v):
            msg = "cpu_limit must match K8s pattern (e.g. 1000m, 500m)"
            raise ValueError(msg)
        return v
