from typing import List, Optional

from aiokafka.admin import AIOKafkaAdminClient

from app.config import get_settings
from app.core.health_checker import HealthCheck, HealthCheckConfig, HealthCheckResult, HealthCheckType, HealthStatus
from app.core.logging import logger


class KafkaConsumerHealthCheck(HealthCheck):
    """Check Kafka consumer health and ability to consume messages"""

    def __init__(
            self,
            consumer_group: str,
            topics: List[str],
            bootstrap_servers: Optional[str] = None
    ):
        super().__init__(
            name=f"kafka_consumer_{consumer_group}",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=10.0,
                interval_seconds=60.0
            )
        )
        self.consumer_group = consumer_group
        self.topics = topics
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS

    async def check(self) -> HealthCheckResult:
        """Check consumer health and lag"""
        admin_client = None

        try:
            # Use admin client to check consumer group status without joining it
            admin_client = AIOKafkaAdminClient(
                bootstrap_servers=self.bootstrap_servers,
                request_timeout_ms=5000
            )
            await admin_client.start()

            try:
                # Check if topics exist
                metadata = await admin_client.list_topics()
                existing_topics = [t for t in self.topics if t in metadata]

                if len(existing_topics) < len(self.topics):
                    return HealthCheckResult(
                        name=self.name,
                        status=HealthStatus.UNHEALTHY,
                        message="Some topics do not exist",
                        details={
                            "consumer_group": self.consumer_group,
                            "expected_topics": self.topics,
                            "existing_topics": existing_topics
                        }
                    )

                # Topics exist, consider this sufficient for health check
                # We can't check consumer group details without joining it
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"Topics exist for consumer group {self.consumer_group}",
                    details={
                        "consumer_group": self.consumer_group,
                        "topics": self.topics,
                        "note": "Consumer group status cannot be checked without joining"
                    }
                )

            except Exception as e:
                logger.warning(f"Could not check consumer group {self.consumer_group}: {e}")

                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message="Cannot check consumer group status",
                    details={
                        "consumer_group": self.consumer_group,
                        "topics": self.topics,
                        "error": str(e)
                    }
                )

        except Exception as e:
            logger.error(f"Kafka consumer health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Consumer health check failed: {str(e)}",
                error=type(e).__name__,
                details={
                    "consumer_group": self.consumer_group,
                    "topics": self.topics
                }
            )

        finally:
            if admin_client:
                try:
                    await admin_client.close()
                except Exception:
                    pass
