"""Centralized health check service for all components"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from kubernetes import client
from kubernetes import config as k8s_config

from app.core.health_checker import (
    CompositeHealthCheck,
    HealthCheck,
    HealthCheckConfig,
    HealthCheckResult,
    HealthCheckType,
    HealthStatus,
    get_health_check_manager,
)
from app.core.logging import logger
from app.dlq.health_check import DLQHealthCheck, DLQProcessingHealthCheck
from app.events.kafka.health_check.create_hcs import create_kafka_health_checks
from app.events.store.event_store import get_event_store
from app.services.idempotency import get_idempotency_manager
from app.websocket.event_handler import WebSocketEventHandler


def _create_health_result(
    name: str,
    health_data: Dict[str, Any],
    healthy_message: str,
    unhealthy_status: HealthStatus = HealthStatus.UNHEALTHY
) -> HealthCheckResult:
    """Create health check result based on health data.
    
    Args:
        name: Check name
        health_data: Health check data with 'healthy' key
        healthy_message: Message when healthy
        unhealthy_status: Status when unhealthy (default UNHEALTHY, can be DEGRADED)
        
    Returns:
        HealthCheckResult
    """
    if health_data.get("healthy"):
        return HealthCheckResult(
            name=name,
            status=HealthStatus.HEALTHY,
            message=healthy_message,
            details=health_data
        )
    else:
        return HealthCheckResult(
            name=name,
            status=unhealthy_status,
            message=f"{name} is {unhealthy_status.value}",
            details=health_data
        )


class MongoDBHealthCheck(HealthCheck):
    """Health check for MongoDB connectivity"""

    def __init__(self, db_manager: Optional[Any] = None) -> None:
        super().__init__(
            name="mongodb",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=5.0,
                interval_seconds=30.0
            )
        )
        self.db_manager = db_manager

    async def check(self) -> HealthCheckResult:
        """Check MongoDB health"""
        try:
            if self.db_manager is None or self.db_manager.db is None:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Database manager not initialized"
                )

            db = self.db_manager.get_database()

            # Ping MongoDB
            result = await db.command("ping")

            if result.get("ok") == 1:
                # Get additional stats
                stats = await db.command("serverStatus")

                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message="MongoDB is healthy",
                    details={
                        "version": stats.get("version"),
                        "uptime": stats.get("uptime"),
                        "connections": {
                            "current": stats.get("connections", {}).get("current"),
                            "available": stats.get("connections", {}).get("available")
                        }
                    }
                )
            else:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="MongoDB ping failed"
                )

        except Exception as e:
            logger.error(f"MongoDB health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to MongoDB: {str(e)}",
                error=type(e).__name__
            )




class KubernetesHealthCheck(HealthCheck):
    """Health check for Kubernetes API connectivity"""

    def __init__(self) -> None:
        super().__init__(
            name="kubernetes",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=10.0,
                interval_seconds=60.0
            )
        )

    async def check(self) -> HealthCheckResult:
        """Check Kubernetes API health"""
        try:
            # Load config
            try:
                k8s_config.load_incluster_config()
            except Exception as e:
                logger.debug(f"Failed to load in-cluster config, trying local config: {e}")
                k8s_config.load_kube_config()

            # Create API client
            v1 = client.CoreV1Api()

            # List namespaces as health check (sync call)
            namespaces = v1.list_namespace()

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"Kubernetes API is healthy, {len(namespaces.items)} namespaces found",
                details={
                    "namespace_count": len(namespaces.items),
                    "api_version": namespaces.api_version
                }
            )

        except Exception as e:
            logger.error(f"Kubernetes health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to Kubernetes API: {str(e)}",
                error=type(e).__name__
            )


class EventStoreHealthCheck(HealthCheck):
    """Health check for Event Store"""

    def __init__(self) -> None:
        super().__init__(
            name="event_store",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=5.0,
                interval_seconds=30.0
            )
        )

    async def check(self) -> HealthCheckResult:
        """Check Event Store health"""
        try:
            event_store = get_event_store()
            if event_store is None:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Event Store not initialized"
                )
            health = await event_store.health_check()

            return _create_health_result(
                name=self.name,
                health_data=health,
                healthy_message="Event Store is healthy"
            )

        except Exception as e:
            logger.error(f"Event Store health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Event Store error: {str(e)}",
                error=type(e).__name__
            )


class WebSocketHealthCheck(HealthCheck):
    """Health check for WebSocket connections"""

    def __init__(self) -> None:
        super().__init__(
            name="websocket",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=2.0,
                interval_seconds=30.0
            ),
            critical=False
        )

    async def check(self) -> HealthCheckResult:
        """Check WebSocket handler health"""
        try:
            # Create instance or get singleton
            handler = WebSocketEventHandler()
            health = await handler.health_check()

            return _create_health_result(
                name=self.name,
                health_data=health,
                healthy_message=f"WebSocket handler is healthy with {health.get('active_connections', 0)} connections",
                unhealthy_status=HealthStatus.DEGRADED
            )

        except Exception as e:
            logger.error(f"WebSocket health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"WebSocket error: {str(e)}",
                error=type(e).__name__
            )


class IdempotencyHealthCheck(HealthCheck):
    """Health check for Idempotency Manager"""

    def __init__(self) -> None:
        super().__init__(
            name="idempotency",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=3.0,
                interval_seconds=60.0
            ),
            critical=False
        )

    async def check(self) -> HealthCheckResult:
        """Check Idempotency Manager health"""
        try:
            manager = get_idempotency_manager()
            if manager is None:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="Idempotency Manager not initialized"
                )
            health = await manager.health_check()

            return _create_health_result(
                name=self.name,
                health_data=health,
                healthy_message="Idempotency Manager is healthy",
                unhealthy_status=HealthStatus.DEGRADED
            )

        except Exception as e:
            logger.error(f"Idempotency health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Idempotency error: {str(e)}",
                error=type(e).__name__
            )


async def initialize_health_checks(db_manager: Optional[Any] = None) -> None:
    """Initialize all health checks and register with manager"""
    manager = get_health_check_manager()

    # Core infrastructure checks
    manager.register_check(MongoDBHealthCheck(db_manager))


    # Kubernetes check
    manager.register_check(KubernetesHealthCheck())

    # Event system checks
    manager.register_check(EventStoreHealthCheck())
    manager.register_check(WebSocketHealthCheck())
    manager.register_check(IdempotencyHealthCheck())

    # Kafka health checks
    kafka_checks = await create_kafka_health_checks()
    for check in kafka_checks:
        manager.register_check(check)

    # DLQ health checks
    manager.register_check(DLQHealthCheck())
    manager.register_check(DLQProcessingHealthCheck())

    # Create composite checks
    infrastructure_check = CompositeHealthCheck(
        name="infrastructure",
        checks=[
            check for check in manager._checks.values()
            if check.name in ["mongodb", "kubernetes"]
        ],
        require_all=False  # Some infrastructure might be optional
    )
    manager.register_check(infrastructure_check)

    event_system_check = CompositeHealthCheck(
        name="event_system",
        checks=[
            check for check in manager._checks.values()
            if check.name.startswith("kafka") or
               check.name in ["event_store", "websocket", "idempotency", "dlq", "dlq_processing"]
        ],
        require_all=False
    )
    manager.register_check(event_system_check)

    # Start periodic health checks
    await manager.start()

    logger.info("Health check system initialized")


async def shutdown_health_checks() -> None:
    """Shutdown health check system"""
    manager = get_health_check_manager()
    await manager.stop()
    logger.info("Health check system shut down")


async def get_health_summary() -> Dict[str, Any]:
    """Get summary of all health checks"""
    manager = get_health_check_manager()

    # Run all checks
    results = await manager.run_all_checks()

    # Categorize results
    summary: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_status": manager.get_overall_status(),
        "categories": {
            "infrastructure": {},
            "kafka": {},
            "event_system": {},
            "workers": {}
        },
        "statistics": {
            "total_checks": len(results),
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "unknown": 0
        }
    }

    # Process each result
    for name, result in results.items():
        # Update statistics
        status_key = result.status.value if hasattr(result.status, 'value') else str(result.status)
        if status_key in summary["statistics"]:
            summary["statistics"][status_key] += 1

        # Categorize
        if name in ["mongodb", "kubernetes"]:
            category = "infrastructure"
        elif name.startswith("kafka"):
            category = "kafka"
        elif name.startswith("consumer_") or name in ["coordinator", "k8s-worker"]:
            category = "workers"
        else:
            category = "event_system"

        if category in summary["categories"]:
            summary["categories"][category][name] = {
                "status": result.status,
                "message": result.message,
                "duration_ms": result.duration_ms,
                "details": result.details
            }

    return summary
