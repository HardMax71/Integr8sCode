from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis
from dishka import AsyncContainer
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logging import logger
from app.core.startup import initialize_metrics_context, initialize_rate_limits
from app.core.tracing import init_tracing
from app.db.schema.schema_manager import SchemaManager
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.sse.partitioned_event_router import PartitionedSSERouter
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

    # Metrics are now initialized directly by each service that needs them
    logger.info("OpenTelemetry metrics will be initialized by individual services")

    # Initialize tracing
    instrumentation_report = init_tracing(
        service_name=settings.TRACING_SERVICE_NAME,
        service_version=settings.TRACING_SERVICE_VERSION,
        sampling_rate=settings.TRACING_SAMPLING_RATE,
        enable_console_exporter=settings.TESTING,
        adaptive_sampling=settings.TRACING_ADAPTIVE_SAMPLING
    )

    if instrumentation_report.has_failures():
        logger.warning(
            "Some instrumentation libraries failed to initialize",
            extra={"instrumentation_summary": instrumentation_report.get_summary()}
        )
    else:
        logger.info(
            "Distributed tracing initialized successfully",
            extra={"instrumentation_summary": instrumentation_report.get_summary()}
        )

    # Initialize schema registry once at startup
    container: AsyncContainer = app.state.dishka_container
    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Initialize database schema once per app startup
    database = await container.get(AsyncIOMotorDatabase)
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

    # Start SSE router to ensure consumers are running before any events are published
    _ = await container.get(PartitionedSSERouter)
    logger.info("SSE router started with consumer pool")

    # All services initialized by dishka providers
    logger.info("All services initialized by dishka providers")

    # Note: Daemonset creation is now handled by k8s_worker service

    try:
        yield
    finally:
        # Dishka automatically handles cleanup of all resources!
        logger.info("Application shutdown complete")
