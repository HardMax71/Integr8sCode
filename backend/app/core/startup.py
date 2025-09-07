import redis.asyncio as redis
from dishka import AsyncContainer

from app.core.logging import logger
from app.core.metrics import (
    ConnectionMetrics,
    CoordinatorMetrics,
    DatabaseMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    HealthMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.core.metrics.context import MetricsContext, get_rate_limit_metrics
from app.domain.rate_limit import RateLimitConfig
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings


async def initialize_metrics_context(container: AsyncContainer) -> None:
    try:
        # Get all metrics from the container
        # These are created as APP-scoped singletons by providers
        metrics_mapping = {}

        # Only add metrics that are actually provided by the container
        # Some metrics might not be needed for certain deployments
        metrics_mapping['event'] = await container.get(EventMetrics)
        metrics_mapping['connection'] = await container.get(ConnectionMetrics)
        metrics_mapping['rate_limit'] = await container.get(RateLimitMetrics)
        metrics_mapping['execution'] = await container.get(ExecutionMetrics)
        metrics_mapping['database'] = await container.get(DatabaseMetrics)
        metrics_mapping['health'] = await container.get(HealthMetrics)
        metrics_mapping['kubernetes'] = await container.get(KubernetesMetrics)
        metrics_mapping['coordinator'] = await container.get(CoordinatorMetrics)
        metrics_mapping['dlq'] = await container.get(DLQMetrics)
        metrics_mapping['notification'] = await container.get(NotificationMetrics)
        metrics_mapping['replay'] = await container.get(ReplayMetrics)
        metrics_mapping['security'] = await container.get(SecurityMetrics)

        # Initialize the context with available metrics
        MetricsContext.initialize_all(**metrics_mapping)

        logger.info(f"Initialized metrics context with {len(metrics_mapping)} metric types")

    except Exception as e:
        logger.error(f"Failed to initialize metrics context: {e}")
        # Don't fail startup if metrics init fails
        # The context will lazy-initialize metrics as needed


async def initialize_rate_limits(
        redis_client: redis.Redis,
        settings: Settings
) -> None:
    """
    Initialize default rate limits in Redis on application startup.
    This ensures default limits are always available.
    """
    try:
        # Create metrics instance
        metrics = get_rate_limit_metrics()
        service = RateLimitService(redis_client, settings, metrics)

        # Check if config already exists
        config_key = f"{settings.RATE_LIMIT_REDIS_PREFIX}config"
        existing_config = await redis_client.get(config_key)

        if not existing_config:
            logger.info("Initializing default rate limit configuration in Redis")

            # Get default config and save it
            default_config = RateLimitConfig.get_default_config()
            await service.update_config(default_config)

            logger.info(f"Initialized {len(default_config.default_rules)} default rate limit rules")
        else:
            logger.info("Rate limit configuration already exists in Redis")

    except Exception as e:
        logger.error(f"Failed to initialize rate limits: {e}")
        # Don't fail startup if rate limit init fails
        # The service will use defaults if Redis is unavailable
