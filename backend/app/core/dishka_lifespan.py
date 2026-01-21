import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from beanie import init_beanie
from dishka import AsyncContainer
from fastapi import FastAPI

from app.core.database_context import Database
from app.core.metrics import RateLimitMetrics
from app.core.startup import initialize_rate_limits
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.events.core import UnifiedProducer
from app.events.event_store_consumer import EventStoreConsumer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.event_bus import EventBus
from app.services.notification_service import NotificationService
from app.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan with dishka dependency injection.

    All service lifecycle (start/stop, background tasks) is managed by DI providers.
    Lifespan only:
    1. Resolves dependencies (triggers provider lifecycle setup)
    2. Initializes schemas and beanie
    3. On shutdown, container cleanup handles everything

    Note: SSE Kafka consumers are now in the separate SSE bridge worker (run_sse_bridge.py).
    """
    container: AsyncContainer = app.state.dishka_container
    settings = await container.get(Settings)
    logger = await container.get(logging.Logger)

    logger.info(
        "Starting application with dishka DI",
        extra={
            "project_name": settings.PROJECT_NAME,
            "environment": "test" if settings.TESTING else "production",
        },
    )

    # Initialize tracing only when enabled
    if settings.ENABLE_TRACING and not settings.TESTING:
        instrumentation_report = init_tracing(
            service_name=settings.TRACING_SERVICE_NAME,
            settings=settings,
            logger=logger,
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
    else:
        logger.info(
            "Distributed tracing disabled",
            extra={"testing": settings.TESTING, "enable_tracing": settings.ENABLE_TRACING},
        )

    # Phase 1: Resolve all DI dependencies in parallel
    # This triggers async generator providers which start services and background tasks
    (
        schema_registry,
        database,
        redis_client,
        rate_limit_metrics,
        _event_store_consumer,
        _notification_service,
        _kafka_producer,
        _event_bus,
    ) = await asyncio.gather(
        container.get(SchemaRegistryManager),
        container.get(Database),
        container.get(redis.Redis),
        container.get(RateLimitMetrics),
        container.get(EventStoreConsumer),
        container.get(NotificationService),
        container.get(UnifiedProducer),
        container.get(EventBus),
    )

    # Phase 2: Initialize infrastructure
    await asyncio.gather(
        initialize_event_schemas(schema_registry),
        init_beanie(database=database, document_models=ALL_DOCUMENTS),
        initialize_rate_limits(redis_client, settings, logger, rate_limit_metrics),
    )
    logger.info("Application started - all services running")

    try:
        yield
    finally:
        # Container cleanup handles all service shutdown via async generator cleanup
        logger.info("Application shutting down - container cleanup will stop all services")
