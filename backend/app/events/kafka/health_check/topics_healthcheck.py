from typing import Any, Dict, List, Optional

from aiokafka.admin import AIOKafkaAdminClient

from app.config import get_settings
from app.core.health_checker import HealthCheck, HealthCheckConfig, HealthCheckResult, HealthCheckType, HealthStatus
from app.core.logging import logger


class KafkaTopicsHealthCheck(HealthCheck):
    """Check if required Kafka topics exist and are accessible"""

    def __init__(
            self,
            required_topics: List[str],
            bootstrap_servers: Optional[str] = None
    ):
        super().__init__(
            name="kafka_topics",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=10.0,
                interval_seconds=60.0
            )
        )
        self.required_topics = required_topics
        settings = get_settings()
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS

    async def check(self) -> HealthCheckResult:
        """Check if required topics exist"""
        admin_client = None

        try:
            admin_client = AIOKafkaAdminClient(
                bootstrap_servers=self.bootstrap_servers,
                request_timeout_ms=10000
            )

            await admin_client.start()

            # List existing topics
            topic_metadata = await admin_client.list_topics()
            existing_topics = set(topic_metadata)

            # Check required topics
            missing_topics = []
            topic_details: Dict[str, Any] = {}

            for topic in self.required_topics:
                if topic not in existing_topics:
                    missing_topics.append(topic)
                else:
                    # Get topic details
                    try:
                        partitions = await admin_client.describe_topics([topic])
                        if topic in partitions:
                            topic_info = partitions[topic]
                            topic_details[topic] = {
                                "partitions": len(topic_info.partitions),
                                "replicas": len(topic_info.partitions[0].replicas) if topic_info.partitions else 0
                            }
                    except Exception as e:
                        logger.warning(f"Could not describe topic {topic}: {e}")
                        topic_details[topic] = {"error": str(e)}

            await admin_client.close()

            if missing_topics:
                return HealthCheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Missing required topics: {', '.join(missing_topics)}",
                    details={
                        "required_topics": self.required_topics,
                        "existing_topics": list(existing_topics),
                        "missing_topics": missing_topics,
                        "topic_details": topic_details
                    }
                )

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"All {len(self.required_topics)} required topics exist",
                details={
                    "topics": topic_details
                }
            )

        except Exception as e:
            logger.error(f"Kafka topics check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot check Kafka topics: {str(e)}",
                error=type(e).__name__
            )

        finally:
            if admin_client:
                try:
                    await admin_client.close()
                except Exception:
                    pass
