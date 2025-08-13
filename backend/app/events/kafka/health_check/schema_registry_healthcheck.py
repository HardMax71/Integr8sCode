from typing import Optional

from app.config import get_settings
from app.core.health_checker import HealthCheck, HealthCheckConfig, HealthCheckResult, HealthCheckType, HealthStatus
from app.core.logging import logger


class KafkaSchemaRegistryHealthCheck(HealthCheck):
    """Check Schema Registry connectivity and health"""

    def __init__(self, schema_registry_url: Optional[str] = None):
        super().__init__(
            name="kafka_schema_registry",
            check_type=HealthCheckType.READINESS,
            config=HealthCheckConfig(
                timeout_seconds=5.0,
                interval_seconds=60.0
            ),
            critical=False  # Schema registry is not critical for basic operation
        )
        settings = get_settings()
        self.schema_registry_url = schema_registry_url or settings.SCHEMA_REGISTRY_URL

    async def check(self) -> HealthCheckResult:
        """Check Schema Registry health"""
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                # Check Schema Registry health endpoint
                async with session.get(
                        f"{self.schema_registry_url}/subjects",
                        timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        subjects = await response.json()

                        return HealthCheckResult(
                            name=self.name,
                            status=HealthStatus.HEALTHY,
                            message=f"Schema Registry is healthy with {len(subjects)} subjects",
                            details={
                                "url": self.schema_registry_url,
                                "subject_count": len(subjects),
                                "subjects": subjects[:10]  # First 10 subjects
                            }
                        )
                    else:
                        return HealthCheckResult(
                            name=self.name,
                            status=HealthStatus.UNHEALTHY,
                            message=f"Schema Registry returned status {response.status}",
                            details={
                                "url": self.schema_registry_url,
                                "status_code": response.status
                            }
                        )

        except Exception as e:
            logger.error(f"Schema Registry health check failed: {e}")

            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to Schema Registry: {str(e)}",
                error=type(e).__name__,
                details={
                    "url": self.schema_registry_url
                }
            )
