from enum import StrEnum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_current_user, require_admin
from app.core.logging import logger
from app.events.kafka.cb import (
    CircuitBreakerType,
    KafkaCircuitBreakerManager,
)


class CircuitBreakerAction(StrEnum):
    RESET = "reset"
    OPEN = "open"
    CLOSE = "close"


router = APIRouter(prefix="/circuit-breakers", tags=["Circuit Breakers"])


class CircuitBreakerStatus(BaseModel):
    name: str
    state: str
    failure_count: int
    success_count: int
    time_in_state: float
    last_failure_time: Optional[str] = None
    half_open_calls: Optional[int] = None
    half_open_successes: Optional[int] = None
    recent_calls: List[Dict[str, Any]] = []


class CircuitBreakerUpdate(BaseModel):
    action: CircuitBreakerAction


class CircuitBreakerConfigUpdate(BaseModel):
    failure_threshold: Optional[int] = None
    failure_rate_threshold: Optional[float] = None
    timeout: Optional[float] = None
    wait_duration_open: Optional[float] = None
    permitted_calls_in_half_open: Optional[int] = None
    sliding_window_size: Optional[int] = None
    minimum_number_of_calls: Optional[int] = None


# Shared manager instance - in production should be injected
_manager: Optional[KafkaCircuitBreakerManager] = None


def get_manager() -> KafkaCircuitBreakerManager:
    """Get or create circuit breaker manager."""
    global _manager
    if _manager is None:
        _manager = KafkaCircuitBreakerManager()
    return _manager


@router.get("/", response_model=List[CircuitBreakerStatus])
async def list_circuit_breakers(
        current_user: dict = Depends(get_current_user)
) -> List[CircuitBreakerStatus]:
    """List all circuit breakers and their status"""
    manager = get_manager()

    # Get Kafka circuit breaker statuses
    kafka_statuses = await manager.get_all_status()

    statuses = []
    for kafka_status in kafka_statuses:
        status = CircuitBreakerStatus(
            name=kafka_status["service"],
            state=kafka_status["state"],
            failure_count=kafka_status["failure_count"],
            success_count=kafka_status["success_count"],
            time_in_state=0,
            last_failure_time=kafka_status.get("last_failure_time"),
            half_open_calls=kafka_status.get("half_open_attempts")
        )
        statuses.append(status)

    return statuses


@router.get("/{breaker_name}", response_model=CircuitBreakerStatus)
async def get_circuit_breaker(
        breaker_name: str,
        current_user: dict = Depends(get_current_user)
) -> CircuitBreakerStatus:
    """Get detailed status of a specific circuit breaker"""
    manager = get_manager()

    # Get all statuses and find the specific one
    kafka_statuses = await manager.get_all_status()

    for kafka_status in kafka_statuses:
        if kafka_status["service"] == breaker_name:
            return CircuitBreakerStatus(
                name=kafka_status["service"],
                state=kafka_status["state"],
                failure_count=kafka_status["failure_count"],
                success_count=kafka_status["success_count"],
                time_in_state=0,
                last_failure_time=kafka_status.get("last_failure_time"),
                half_open_calls=kafka_status.get("half_open_attempts")
            )

    raise HTTPException(status_code=404, detail="Circuit breaker not found")


@router.post("/{breaker_name}/update")
async def update_circuit_breaker(
        breaker_name: str,
        update: CircuitBreakerUpdate,
        current_user: dict = Depends(require_admin)
) -> Dict[str, str]:
    """Update circuit breaker state (admin only)"""
    manager = get_manager()

    # Parse breaker name to get type and identifier
    if breaker_name.startswith("kafka-producer-"):
        breaker_type = CircuitBreakerType.PRODUCER
        identifier = breaker_name.replace("kafka-producer-", "")
    elif breaker_name.startswith("kafka-consumer-"):
        breaker_type = CircuitBreakerType.CONSUMER
        identifier = breaker_name.replace("kafka-consumer-", "")
    else:
        # Check if it's a general service circuit breaker
        breaker_type = CircuitBreakerType.GENERAL
        identifier = breaker_name

    # Get or create the circuit breaker
    breaker = await manager.get_or_create_breaker(breaker_type, identifier)

    try:
        if update.action == CircuitBreakerAction.RESET:
            await breaker.reset()
            message = f"Circuit breaker {breaker_name} reset to closed state"
        elif update.action == CircuitBreakerAction.OPEN:
            await breaker.open()
            message = f"Circuit breaker {breaker_name} manually opened"
        elif update.action == CircuitBreakerAction.CLOSE:
            await breaker.reset()
            message = f"Circuit breaker {breaker_name} manually closed"

        logger.info(f"{message} by user {current_user['id']}")
        return {"message": message}

    except Exception as e:
        logger.error(f"Failed to update circuit breaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset-all")
async def reset_all_circuit_breakers(
        current_user: dict = Depends(require_admin)
) -> Dict[str, str]:
    """Reset all circuit breakers to closed state (admin only)"""
    manager = get_manager()

    try:
        await manager.reset_all()

        logger.info(f"All circuit breakers reset by user {current_user['id']}")
        return {"message": "All circuit breakers reset to closed state"}

    except Exception as e:
        logger.error(f"Failed to reset all circuit breakers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/check")
async def health_check(
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Check health of all circuit breakers"""
    manager = get_manager()

    kafka_statuses = await manager.get_all_status()

    health = {}
    for kafka_status in kafka_statuses:
        health[kafka_status["service"]] = kafka_status["state"] == "CLOSED"

    all_healthy = all(health.values())

    return {
        "healthy": all_healthy,
        "circuit_breakers": health,
        "unhealthy_count": len([v for v in health.values() if not v])
    }


@router.get("/metrics/summary")
async def get_metrics_summary(
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get summary metrics for all circuit breakers"""
    manager = get_manager()

    kafka_statuses = await manager.get_all_status()

    total = len(kafka_statuses)
    closed = sum(1 for status in kafka_statuses if status["state"] == "CLOSED")
    open_breakers = sum(1 for status in kafka_statuses if status["state"] == "OPEN")
    half_open = sum(1 for status in kafka_statuses if status["state"] == "HALF_OPEN")

    open_list = [s["service"] for s in kafka_statuses if s["state"] == "OPEN"]

    return {
        "total_circuit_breakers": total,
        "states": {
            "closed": closed,
            "open": open_breakers,
            "half_open": half_open
        },
        "health_percentage": (closed / total * 100) if total > 0 else 100,
        "open_circuit_breakers": open_list
    }
