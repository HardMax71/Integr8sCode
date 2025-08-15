from datetime import datetime, timezone
from typing import Optional

from aiokafka import AIOKafkaProducer

from app.config import get_settings
from app.core.health_checker import HealthCheck, HealthCheckConfig, HealthCheckResult, HealthCheckType, HealthStatus
from app.core.logging import logger
from app.events.core.producer import UnifiedProducer


class KafkaProducerHealthCheck(HealthCheck):
    """Check Kafka producer health and ability to send messages"""

    def __init__(
            self,
            producer: Optional[UnifiedProducer] = None,
            test_topic: str = "__health_check__",
            bootstrap_servers: Optional[str] = None
    ):
        super().__init__(
            name="kafka_producer",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=5.0,
                interval_seconds=30.0
            ),
            critical=True
        )
        self._producer = producer
        self.test_topic = test_topic
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS

    async def check(self) -> HealthCheckResult:
        """Check producer health by sending test message"""
        try:
            # Check if producer is available
            if self._producer:
                producer_status = self._producer.get_status()

                # Check if producer is connected
                if not producer_status.get("connected"):
                    raise Exception("Producer not connected")

                # Check circuit breaker if available
                circuit_breaker = producer_status.get("circuit_breaker", {})
                if circuit_breaker.get("state") != "closed":
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.DEGRADED,
                        message=f"Producer circuit breaker is {circuit_breaker.get('state')}",
                        details={
                            "circuit_breaker": circuit_breaker,
                            "retry_queue_size": producer_status.get("retry_queue_size", 0)
                        }
                    )

                # Producer exists and is healthy
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message="Producer is connected and healthy",
                    details={
                        "retry_queue_size": producer_status.get("retry_queue_size", 0),
                        "bootstrap_servers": producer_status.get("bootstrap_servers")
                    }
                )
            else:
                # Producer not available - create temporary producer for health check
                temp_producer = None
                try:
                    temp_producer = AIOKafkaProducer(
                        bootstrap_servers=self.bootstrap_servers,
                        request_timeout_ms=5000,
                        metadata_max_age_ms=10000
                    )

                    await temp_producer.start()

                    # Send test message
                    test_message = {
                        "type": "health_check",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "service": "kafka_producer_health_check"
                    }

                    await temp_producer.send_and_wait(
                        self.test_topic,
                        value=str(test_message).encode('utf-8'),
                        key=b"health_check"
                    )

                    await temp_producer.stop()

                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.HEALTHY,
                        message="Producer can send messages successfully",
                        details={
                            "test_topic": self.test_topic
                        }
                    )
                finally:
                    if temp_producer:
                        try:
                            await temp_producer.stop()
                        except Exception:
                            pass

        except Exception as e:
            logger.error(f"Kafka producer health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Producer cannot send messages: {str(e)}",
                error=type(e).__name__
            )
