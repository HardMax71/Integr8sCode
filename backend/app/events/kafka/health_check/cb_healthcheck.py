"""
Kafka circuit breaker health check implementation.

This module provides health monitoring for Kafka circuit breakers,
reporting on their states and overall system resilience.
"""

from collections import Counter
from typing import Any, Final

from app.core.health_checker import (
    HealthCheck,
    HealthCheckConfig,
    HealthCheckResult,
    HealthCheckType,
    HealthStatus,
)
from app.core.logging import logger
from app.events.kafka.cb import KafkaCircuitBreakerManager

# Constants for circuit breaker states
OPEN_STATE: Final[str] = "OPEN"
HALF_OPEN_STATE: Final[str] = "HALF_OPEN"
CLOSED_STATE: Final[str] = "CLOSED"


class KafkaCircuitBreakerHealthCheck(HealthCheck):
    """
    Health check for Kafka circuit breakers.
    
    Monitors the state of all circuit breakers in the system and reports
    degraded health if any breakers are open or half-open.
    """

    def __init__(self, cb_manager: KafkaCircuitBreakerManager | None = None) -> None:
        """Initialize the circuit breaker health check.
        
        Args:
            cb_manager: Optional circuit breaker manager instance
        """
        super().__init__(
            name="kafka_circuit_breakers",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=2.0,
                interval_seconds=30.0
            )
        )
        self._cb_manager = cb_manager or KafkaCircuitBreakerManager()

    async def check(self) -> HealthCheckResult:
        """
        Check the health of all circuit breakers.
        
        Returns:
            HealthCheckResult indicating the aggregate health status
        """
        try:
            circuit_breakers = await self._cb_manager.get_all_status()
            return self._analyze_circuit_breaker_states(circuit_breakers)
        except Exception as e:
            logger.error(f"Circuit breaker health check failed: {e}")
            return self._create_error_result(e)

    def _analyze_circuit_breaker_states(
        self,
        circuit_breakers: list[dict[str, Any]]
    ) -> HealthCheckResult:
        """
        Analyze circuit breaker states and determine health status.
        
        Args:
            circuit_breakers: List of circuit breaker status dictionaries
            
        Returns:
            HealthCheckResult based on the analysis
        """
        # Group breakers by state
        states_by_service = {
            cb["service"]: cb["state"]
            for cb in circuit_breakers
        }
        
        state_counts = Counter(states_by_service.values())
        problem_services = {
            service: state
            for service, state in states_by_service.items()
            if state != CLOSED_STATE
        }
        
        # Determine health status and message
        match (state_counts.get(OPEN_STATE, 0), state_counts.get(HALF_OPEN_STATE, 0)):
            case (0, 0):
                return self._create_healthy_result(len(circuit_breakers))
            case (open_count, _) if open_count > 0:
                return self._create_degraded_result(
                    problem_services,
                    state_counts,
                    f"{open_count} circuit breakers are open"
                )
            case (0, half_open_count):
                return self._create_degraded_result(
                    problem_services,
                    state_counts,
                    f"{half_open_count} circuit breakers are half-open"
                )
        return self._create_degraded_result(
                    problem_services,
                    state_counts,
                    "ERROR: MATCH-CASE in cb-check IS FAILED!"
                )

    def _create_healthy_result(self, total_breakers: int) -> HealthCheckResult:
        """Create a healthy status result."""
        return HealthCheckResult(
            name=self.name,
            status=HealthStatus.HEALTHY,
            message=f"All {total_breakers} circuit breakers are closed",
            details={"total": total_breakers, "state_summary": {"closed": total_breakers}}
        )

    def _create_degraded_result(
        self,
        problem_services: dict[str, str],
        state_counts: Counter[str],
        message: str
    ) -> HealthCheckResult:
        """Create a degraded status result."""
        return HealthCheckResult(
            name=self.name,
            status=HealthStatus.DEGRADED,
            message=message,
            details={
                "total": sum(state_counts.values()),
                "state_summary": dict(state_counts),
                "problem_services": problem_services
            }
        )

    def _create_error_result(self, error: Exception) -> HealthCheckResult:
        """Create an error status result."""
        return HealthCheckResult(
            name=self.name,
            status=HealthStatus.UNKNOWN,
            message=f"Cannot check circuit breakers: {error}",
            error=type(error).__name__
        )
