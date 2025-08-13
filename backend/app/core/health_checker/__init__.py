"""Health checker module - main entry point for health checking functionality.

This module provides health checking capabilities for monitoring service health.
The implementation is organized into:
- models: Enums and data classes
- base: Base classes and implementations
- manager: Health check orchestration
- metrics.health_check: Metrics definitions (in app.metrics)
"""

# Re-export all components for easy access
from app.core.health_checker.base import (
    CompositeHealthCheck,
    HealthCheck,
    HealthCheckError,
)
from app.core.health_checker.manager import (
    HealthCheckManager,
    get_health_check_manager,
)
from app.core.health_checker.models import (
    HealthCheckConfig,
    HealthCheckResult,
    HealthCheckType,
    HealthStatus,
)

__all__ = [
    # Models
    "HealthStatus",
    "HealthCheckType",
    "HealthCheckResult",
    "HealthCheckConfig",
    # Base classes
    "HealthCheck",
    "CompositeHealthCheck",
    "HealthCheckError",
    # Manager
    "HealthCheckManager",
    "get_health_check_manager",
]
