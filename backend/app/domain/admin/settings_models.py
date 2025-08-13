"""Domain models for admin settings.

This module provides strongly-typed domain models for system settings
to replace Dict[str, Any] usage throughout the admin settings repository.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, Optional


class SettingsFields(StrEnum):
    """Database field names for settings collection."""
    ID = "_id"
    UPDATED_BY = "updated_by"
    UPDATED_AT = "updated_at"
    RATE_LIMITS = "rate_limits"
    KAFKA_SETTINGS = "kafka_settings"
    EXECUTION_LIMITS = "execution_limits"
    SECURITY_SETTINGS = "security_settings"
    MONITORING_SETTINGS = "monitoring_settings"


class AuditLogFields(StrEnum):
    """Database field names for audit log collection."""
    ACTION = "action"
    USER_ID = "user_id"
    USERNAME = "username"
    TIMESTAMP = "timestamp"
    CHANGES = "changes"


class AuditAction(StrEnum):
    """Audit log action types."""
    SYSTEM_SETTINGS_UPDATED = "system_settings_updated"
    SYSTEM_SETTINGS_RESET = "system_settings_reset"


class LogLevel(StrEnum):
    """Log level options."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class RateLimits:
    """Rate limiting configuration."""
    default: str = "100/minute"
    auth: str = "5/minute"
    execution: str = "20/minute"
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for MongoDB."""
        return {
            "default": self.default,
            "auth": self.auth,
            "execution": self.execution
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RateLimits":
        """Create from MongoDB document."""
        if not data:
            return cls()
        return cls(
            default=data.get("default", "100/minute"),
            auth=data.get("auth", "5/minute"),
            execution=data.get("execution", "20/minute")
        )


@dataclass
class KafkaSettings:
    """Kafka configuration settings."""
    retention_days: int = 7
    partition_count: int = 3
    replication_factor: int = 1
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for MongoDB."""
        return {
            "retention_days": self.retention_days,
            "partition_count": self.partition_count,
            "replication_factor": self.replication_factor
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "KafkaSettings":
        """Create from MongoDB document."""
        if not data:
            return cls()
        return cls(
            retention_days=data.get("retention_days", 7),
            partition_count=data.get("partition_count", 3),
            replication_factor=data.get("replication_factor", 1)
        )


@dataclass
class ExecutionLimits:
    """Execution resource limits."""
    max_timeout_seconds: int = 300
    max_memory_mb: int = 512
    max_cpu_cores: int = 2
    max_concurrent_executions: int = 10
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for MongoDB."""
        return {
            "max_timeout_seconds": self.max_timeout_seconds,
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_cores": self.max_cpu_cores,
            "max_concurrent_executions": self.max_concurrent_executions
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionLimits":
        """Create from MongoDB document."""
        if not data:
            return cls()
        return cls(
            max_timeout_seconds=data.get("max_timeout_seconds", 300),
            max_memory_mb=data.get("max_memory_mb", 512),
            max_cpu_cores=data.get("max_cpu_cores", 2),
            max_concurrent_executions=data.get("max_concurrent_executions", 10)
        )


@dataclass
class SecuritySettings:
    """Security configuration settings."""
    password_min_length: int = 8
    session_timeout_minutes: int = 60
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15
    
    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary for MongoDB."""
        return {
            "password_min_length": self.password_min_length,
            "session_timeout_minutes": self.session_timeout_minutes,
            "max_login_attempts": self.max_login_attempts,
            "lockout_duration_minutes": self.lockout_duration_minutes
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SecuritySettings":
        """Create from MongoDB document."""
        if not data:
            return cls()
        return cls(
            password_min_length=data.get("password_min_length", 8),
            session_timeout_minutes=data.get("session_timeout_minutes", 60),
            max_login_attempts=data.get("max_login_attempts", 5),
            lockout_duration_minutes=data.get("lockout_duration_minutes", 15)
        )


@dataclass
class MonitoringSettings:
    """Monitoring and observability settings."""
    metrics_retention_days: int = 30
    log_level: LogLevel = LogLevel.INFO
    enable_tracing: bool = True
    sampling_rate: float = 0.1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        return {
            "metrics_retention_days": self.metrics_retention_days,
            "log_level": self.log_level.value,
            "enable_tracing": self.enable_tracing,
            "sampling_rate": self.sampling_rate
        }
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MonitoringSettings":
        """Create from MongoDB document."""
        if not data:
            return cls()
        return cls(
            metrics_retention_days=data.get("metrics_retention_days", 30),
            log_level=LogLevel(data.get("log_level", LogLevel.INFO)),
            enable_tracing=data.get("enable_tracing", True),
            sampling_rate=data.get("sampling_rate", 0.1)
        )


@dataclass
class SystemSettings:
    """Complete system settings configuration."""
    rate_limits: RateLimits = field(default_factory=RateLimits)
    kafka_settings: KafkaSettings = field(default_factory=KafkaSettings)
    execution_limits: ExecutionLimits = field(default_factory=ExecutionLimits)
    security_settings: SecuritySettings = field(default_factory=SecuritySettings)
    monitoring_settings: MonitoringSettings = field(default_factory=MonitoringSettings)
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        doc: Dict[str, Any] = {
            SettingsFields.ID.value: "global",
            SettingsFields.RATE_LIMITS.value: self.rate_limits.to_dict(),
            SettingsFields.KAFKA_SETTINGS.value: self.kafka_settings.to_dict(),
            SettingsFields.EXECUTION_LIMITS.value: self.execution_limits.to_dict(),
            SettingsFields.SECURITY_SETTINGS.value: self.security_settings.to_dict(),
            SettingsFields.MONITORING_SETTINGS.value: self.monitoring_settings.to_dict()
        }
        
        if self.updated_by:
            doc[SettingsFields.UPDATED_BY.value] = self.updated_by
        if self.updated_at:
            doc[SettingsFields.UPDATED_AT.value] = self.updated_at
            
        return doc
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SystemSettings":
        """Create from MongoDB document."""
        if not data:
            return cls()
            
        return cls(
            rate_limits=RateLimits.from_dict(data.get(SettingsFields.RATE_LIMITS.value)),
            kafka_settings=KafkaSettings.from_dict(data.get(SettingsFields.KAFKA_SETTINGS.value)),
            execution_limits=ExecutionLimits.from_dict(data.get(SettingsFields.EXECUTION_LIMITS.value)),
            security_settings=SecuritySettings.from_dict(data.get(SettingsFields.SECURITY_SETTINGS.value)),
            monitoring_settings=MonitoringSettings.from_dict(data.get(SettingsFields.MONITORING_SETTINGS.value)),
            updated_by=data.get(SettingsFields.UPDATED_BY.value),
            updated_at=data.get(SettingsFields.UPDATED_AT.value)
        )
    
    @classmethod
    def get_defaults(cls) -> "SystemSettings":
        """Get default system settings."""
        return cls()
    
    def to_pydantic_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for Pydantic schema."""
        return {
            "rate_limits": self.rate_limits.to_dict(),
            "kafka_settings": self.kafka_settings.to_dict(),
            "execution_limits": self.execution_limits.to_dict(),
            "security_settings": self.security_settings.to_dict(),
            "monitoring_settings": self.monitoring_settings.to_dict()
        }
    
    @classmethod
    def from_pydantic(cls, pydantic_data: Dict[str, Any]) -> "SystemSettings":
        """Create from Pydantic schema data."""
        return cls(
            rate_limits=RateLimits.from_dict(pydantic_data.get("rate_limits")),
            kafka_settings=KafkaSettings.from_dict(pydantic_data.get("kafka_settings")),
            execution_limits=ExecutionLimits.from_dict(pydantic_data.get("execution_limits")),
            security_settings=SecuritySettings.from_dict(pydantic_data.get("security_settings")),
            monitoring_settings=MonitoringSettings.from_dict(pydantic_data.get("monitoring_settings"))
        )


@dataclass
class AuditLogEntry:
    """Audit log entry for tracking changes."""
    action: AuditAction
    user_id: str
    username: str
    timestamp: datetime
    changes: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB."""
        doc: Dict[str, Any] = {
            AuditLogFields.ACTION.value: self.action.value,
            AuditLogFields.USER_ID.value: self.user_id,
            AuditLogFields.USERNAME.value: self.username,
            AuditLogFields.TIMESTAMP.value: self.timestamp
        }
        
        if self.changes:
            doc[AuditLogFields.CHANGES.value] = self.changes
            
        return doc
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditLogEntry":
        """Create from MongoDB document."""
        return cls(
            action=AuditAction(data.get(AuditLogFields.ACTION.value, "")),
            user_id=data.get(AuditLogFields.USER_ID.value, ""),
            username=data.get(AuditLogFields.USERNAME.value, ""),
            timestamp=data.get(AuditLogFields.TIMESTAMP.value, datetime.now()),
            changes=data.get(AuditLogFields.CHANGES.value)
        )
