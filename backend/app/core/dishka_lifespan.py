from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis
from beanie import init_beanie
from dishka import AsyncContainer
from fastapi import FastAPI

from app.core.database_context import Database
from app.core.metrics import RateLimitMetrics
from app.core.startup import initialize_rate_limits
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.events.event_store_consumer import EventStoreConsumer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.notification_service import NotificationService
from app.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan with dishka dependency injection.

    This is much cleaner than the old lifespan.py:
    - No dependency_overrides
    - No manual service management
    - Dishka handles all lifecycle automatically
    """
    # Get settings and logger from DI container (uses test settings in tests)
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

    # Metrics setup moved to app creation to allow middleware registration
    logger.info("Lifespan start: tracing and services initialization")

    # Initialize tracing only when enabled (avoid exporter retries in tests)
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
    # SSE bus + consumers start automatically via NotificationService's dependency on SSERedisBus
    (
        schema_registry,
        database,
        redis_client,
        rate_limit_metrics,
        event_store_consumer,
        notification_service,
    ) = await asyncio.gather(
        container.get(SchemaRegistryManager),
        container.get(Database),
        container.get(redis.Redis),
        container.get(RateLimitMetrics),
        container.get(EventStoreConsumer),
        container.get(NotificationService),
    )

    # Phase 2: Initialize infrastructure in parallel (independent subsystems)
    await asyncio.gather(
        initialize_event_schemas(schema_registry),
        init_beanie(database=database, document_models=ALL_DOCUMENTS),
        initialize_rate_limits(redis_client, settings, logger, rate_limit_metrics),
    )
    logger.info("Infrastructure initialized (schemas, beanie, rate limits)")

    # Phase 3: Start lifecycle-managed services
    # SSE bridge consumers are started by the DI provider — no lifecycle to manage here
    async with AsyncExitStack() as stack:
        stack.push_async_callback(event_store_consumer.aclose)
        stack.push_async_callback(notification_service.aclose)
        await asyncio.gather(
            event_store_consumer.__aenter__(),
            notification_service.__aenter__(),
        )
        logger.info("EventStoreConsumer and NotificationService started")
        yield
