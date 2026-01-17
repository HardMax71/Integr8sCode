import logging

import redis.asyncio as redis

from app.core.metrics import RateLimitMetrics
from app.domain.rate_limit import RateLimitConfig
from app.services.rate_limit_service import RateLimitService
from app.settings import Settings


async def initialize_rate_limits(
    redis_client: redis.Redis,
    settings: Settings,
    logger: logging.Logger,
    rate_limit_metrics: RateLimitMetrics,
) -> None:
    """
    Initialize default rate limits in Redis on application startup.
    This ensures default limits are always available.
    """
    try:
        service = RateLimitService(redis_client, settings, rate_limit_metrics)

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
