import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MEMORY_PATTERN = re.compile(r"^[1-9]\d*(Mi|Gi|Ki)$")
_CPU_PATTERN = re.compile(r"^[1-9]\d*m$")


class SystemSettingsSchema(BaseModel):
    """API schema for system settings with validation."""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    max_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    memory_limit: str = "512Mi"
    cpu_limit: str = "2000m"
    max_concurrent_executions: int = Field(default=10, ge=1, le=100)
    max_executions_per_user: int = Field(default=100, ge=1, le=1000)

    password_min_length: int = Field(default=8, ge=8, le=32)
    session_timeout_minutes: int = Field(default=60, ge=5, le=1440)
    max_login_attempts: int = Field(default=5, ge=3, le=10)
    lockout_duration_minutes: int = Field(default=15, ge=5, le=60)

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
