from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis
from dishka import AsyncContainer
from fastapi import FastAPI

from app.core.database_context import Database
from app.core.logging import logger
from app.core.startup import initialize_metrics_context, initialize_rate_limits
from app.core.tracing import init_tracing
from app.db.schema.schema_manager import SchemaManager
from app.events.event_store_consumer import EventStoreConsumer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan with dishka dependency injection.

    This is much cleaner than the old lifespan.py:
    - No dependency_overrides
    - No manual service management
    - Dishka handles all lifecycle automatically
    """
    settings = get_settings()
    logger.info(
        "Starting application with dishka DI",
        extra={
            "project_name": settings.PROJECT_NAME,
            "environment": "test" if settings.TESTING else "production",
        },
    )

    # Metrics setup moved to app creation to allow middleware registration
    logger.info("Lifespan start: tracing and services initialization")

    # Initialize tracing
    instrumentation_report = init_tracing(
        service_name=settings.TRACING_SERVICE_NAME,
        service_version=settings.TRACING_SERVICE_VERSION,
        sampling_rate=settings.TRACING_SAMPLING_RATE,
        enable_console_exporter=settings.TESTING,
        adaptive_sampling=settings.TRACING_ADAPTIVE_SAMPLING,
    )

    if instrumentation_report.has_failures():
        logger.warning(
            "Some instrumentation libraries failed to initialize",
            extra={"instrumentation_summary": instrumentation_report.get_summary()},
        )
    else:
        logger.info(
            "Distributed tracing initialized successfully",
            extra={"instrumentation_summary": instrumentation_report.get_summary()},
        )

    # Initialize schema registry once at startup
    container: AsyncContainer = app.state.dishka_container
    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Initialize database schema at application scope using app-scoped DB
    database = await container.get(Database)
    schema_manager = SchemaManager(database)
    await schema_manager.apply_all()
    logger.info("Database schema ensured by SchemaManager")

    # Initialize metrics context with instances from DI container
    # This must happen early so services can access metrics via contextvars
    await initialize_metrics_context(container)
    logger.info("Metrics context initialized with contextvars")

    # Initialize default rate limits in Redis
    redis_client = await container.get(redis.Redis)
    await initialize_rate_limits(redis_client, settings)
    logger.info("Rate limits initialized in Redis")

    # Rate limit middleware added during app creation; service resolved lazily at runtime

    # Acquire long-lived services and manage lifecycle via AsyncExitStack
    sse_bridge = await container.get(SSEKafkaRedisBridge)
    event_store_consumer = await container.get(EventStoreConsumer)

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(sse_bridge)
        logger.info("SSE Kafka→Redis bridge started with consumer pool")
        await stack.enter_async_context(event_store_consumer)
        logger.info("EventStoreConsumer started - events will be persisted to MongoDB")
        logger.info("All services initialized by DI and managed by AsyncExitStack")
        yield
