"""Health checks for Dead Letter Queue"""

from datetime import datetime, timezone

from app.core.health_checker import HealthCheck, HealthCheckConfig, HealthCheckResult, HealthCheckType, HealthStatus
from app.core.logging import logger
from app.dlq.manager import get_dlq_manager


class DLQHealthCheck(HealthCheck):
    """Health check for Dead Letter Queue"""

    def __init__(
        self,
        warning_threshold: int = 100,
        critical_threshold: int = 1000,
        max_age_hours: int = 24,
    ):
        super().__init__(
            name="dlq",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                interval_seconds=60.0,
                timeout_seconds=10.0,
                cache_duration_seconds=30.0
            ),
            critical=False
        )
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.max_age_hours = max_age_hours

    async def check(self) -> HealthCheckResult:
        """Check DLQ health"""
        try:
            dlq_manager = await get_dlq_manager()
            stats = await dlq_manager.get_dlq_stats()

            # Calculate total messages
            status_counts = stats.get("by_status", {})
            total_messages = sum(status_counts.values())
            pending_messages = status_counts.get("pending", 0) + status_counts.get("scheduled", 0)

            # Check message age
            age_stats = stats.get("age_stats", {})
            oldest_message = age_stats.get("oldest_message")

            message_age_hours = 0
            if oldest_message:
                if isinstance(oldest_message, str):
                    oldest_message = datetime.fromisoformat(oldest_message)
                message_age = datetime.now(timezone.utc) - oldest_message
                message_age_hours = message_age.total_seconds() / 3600

            # Determine health status
            if total_messages >= self.critical_threshold:
                status = HealthStatus.UNHEALTHY
                message = f"Critical: {total_messages} messages in DLQ (threshold: {self.critical_threshold})"
            elif total_messages >= self.warning_threshold:
                status = HealthStatus.DEGRADED
                message = f"Warning: {total_messages} messages in DLQ (threshold: {self.warning_threshold})"
            elif message_age_hours > self.max_age_hours and total_messages > 0:
                status = HealthStatus.DEGRADED
                message = f"Warning: Oldest message is {message_age_hours:.1f} hours old"
            else:
                status = HealthStatus.HEALTHY
                message = f"DLQ healthy with {total_messages} messages"

            # Prepare details
            details = {
                "total_messages": total_messages,
                "pending_messages": pending_messages,
                "status_breakdown": status_counts,
                "topics": [
                    {
                        "topic": item["_id"],
                        "count": item["count"],
                        "avg_retries": item.get("avg_retry_count", 0)
                    }
                    for item in stats.get("by_topic", [])
                ],
                "oldest_message_hours": round(message_age_hours, 2) if message_age_hours else 0,
                "thresholds": {
                    "warning": self.warning_threshold,
                    "critical": self.critical_threshold,
                    "max_age_hours": self.max_age_hours
                }
            }

            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                details=details
            )

        except Exception as e:
            logger.error(f"DLQ health check failed: {e}")
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"DLQ health check failed: {str(e)}",
                error=type(e).__name__
            )


class DLQProcessingHealthCheck(HealthCheck):
    """Health check for DLQ processing"""

    def __init__(self) -> None:
        super().__init__(
            name="dlq_processing",
            check_type=HealthCheckType.LIVENESS,
            config=HealthCheckConfig(
                interval_seconds=30.0,
                timeout_seconds=5.0
            ),
            critical=False
        )

    async def check(self) -> HealthCheckResult:
        """Check if DLQ processing is working"""
        try:
            dlq_manager = await get_dlq_manager()

            # Check if manager is running
            if not dlq_manager._running:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message="DLQ manager not running"
                )

            # Check if processing tasks are alive
            tasks_healthy = True
            task_status = {}

            if dlq_manager._process_task:
                task_status["process_task"] = not dlq_manager._process_task.done()
                if dlq_manager._process_task.done():
                    tasks_healthy = False

            if dlq_manager._monitor_task:
                task_status["monitor_task"] = not dlq_manager._monitor_task.done()
                if dlq_manager._monitor_task.done():
                    tasks_healthy = False

            # Check Kafka connections
            kafka_healthy = True
            kafka_status = {}

            if dlq_manager.consumer:
                try:
                    # Simple check - get partitions
                    partitions = dlq_manager.consumer.partitions_for_topic(dlq_manager.dlq_topic)
                    kafka_status["consumer"] = "connected"
                    kafka_status["partitions"] = str(len(partitions) if partitions else 0)
                except Exception as e:
                    kafka_healthy = False
                    kafka_status["consumer"] = f"error: {str(e)}"

            if dlq_manager.producer:
                kafka_status["producer"] = "connected"

            # Determine overall status
            if not tasks_healthy:
                status = HealthStatus.UNHEALTHY
                message = "DLQ processing tasks failed"
            elif not kafka_healthy:
                status = HealthStatus.DEGRADED
                message = "DLQ Kafka connection issues"
            else:
                status = HealthStatus.HEALTHY
                message = "DLQ processing healthy"

            return HealthCheckResult(
                name=self.name,
                status=status,
                message=message,
                details={
                    "tasks": task_status,
                    "kafka": kafka_status,
                    "dlq_topic": dlq_manager.dlq_topic
                }
            )

        except Exception as e:
            logger.error(f"DLQ processing health check failed: {e}")
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
                error=type(e).__name__
            )
