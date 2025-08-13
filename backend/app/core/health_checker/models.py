"""Health check models, enums, and data classes."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, Optional


class HealthStatus(StrEnum):
    """Health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckType(StrEnum):
    """Health check type enumeration."""
    STARTUP = "startup"
    LIVENESS = "liveness"
    READINESS = "readiness"


@dataclass
class HealthCheckResult:
    """Result of a health check execution."""
    name: str
    status: HealthStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        """Check if result indicates healthy status."""
        return self.status == HealthStatus.HEALTHY

    @property
    def is_degraded(self) -> bool:
        """Check if result indicates degraded status."""
        return self.status == HealthStatus.DEGRADED

    @property
    def is_unhealthy(self) -> bool:
        """Check if result indicates unhealthy status."""
        return self.status == HealthStatus.UNHEALTHY


@dataclass
class HealthCheckConfig:
    """Configuration for health checks."""
    interval_seconds: float = 30.0
    timeout_seconds: float = 10.0
    startup_delay_seconds: float = 5.0
    failure_threshold: int = 3
    success_threshold: int = 1
    cache_duration_seconds: float = 5.0
    retry_count: int = 2
    retry_delay_seconds: float = 1.0
