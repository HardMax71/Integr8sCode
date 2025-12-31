from pydantic import BaseModel, ConfigDict, Field


class ExecutionLimitsSchema(BaseModel):
    """Execution resource limits schema."""

    model_config = ConfigDict(from_attributes=True)

    max_timeout_seconds: int = Field(default=300, ge=10, le=3600, description="Maximum execution timeout")
    max_memory_mb: int = Field(default=512, ge=128, le=4096, description="Maximum memory in MB")
    max_cpu_cores: int = Field(default=2, ge=1, le=8, description="Maximum CPU cores")
    max_concurrent_executions: int = Field(default=10, ge=1, le=100, description="Maximum concurrent executions")


class SecuritySettingsSchema(BaseModel):
    """Security configuration schema."""

    model_config = ConfigDict(from_attributes=True)

    password_min_length: int = Field(default=8, ge=6, le=32, description="Minimum password length")
    session_timeout_minutes: int = Field(default=60, ge=5, le=1440, description="Session timeout in minutes")
    max_login_attempts: int = Field(default=5, ge=3, le=10, description="Maximum login attempts")
    lockout_duration_minutes: int = Field(default=15, ge=5, le=60, description="Account lockout duration")


class MonitoringSettingsSchema(BaseModel):
    """Monitoring and observability schema."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    metrics_retention_days: int = Field(default=30, ge=7, le=90, description="Metrics retention in days")
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Log level")
    enable_tracing: bool = Field(default=True, description="Enable distributed tracing")
    sampling_rate: float = Field(default=0.1, ge=0.0, le=1.0, description="Trace sampling rate")


class SystemSettings(BaseModel):
    """System-wide settings model."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    execution_limits: ExecutionLimitsSchema = Field(default_factory=ExecutionLimitsSchema)
    security_settings: SecuritySettingsSchema = Field(default_factory=SecuritySettingsSchema)
    monitoring_settings: MonitoringSettingsSchema = Field(default_factory=MonitoringSettingsSchema)
