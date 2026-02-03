from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as redis
from beanie import init_beanie
from dishka import AsyncContainer
from fastapi import FastAPI
from faststream.kafka import KafkaBroker

from app.core.database_context import Database
from app.core.metrics import RateLimitMetrics
from app.core.startup import initialize_rate_limits
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.notification_scheduler import NotificationScheduler
from app.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan with dishka dependency injection.

    Kafka broker lifecycle is managed here (start/stop).
    Consumers start when the broker starts; dishka handles all DI.
    """
    # Get settings and logger from DI container (uses test settings in tests)
    container: AsyncContainer = app.state.dishka_container
    broker: KafkaBroker = app.state.kafka_broker
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

    # Phase 1: Resolve DI dependencies
    # NotificationScheduler starts APScheduler automatically via its DI provider
    (
        schema_registry,
        database,
        redis_client,
        rate_limit_metrics,
        _notification_scheduler,
    ) = await asyncio.gather(
        container.get(SchemaRegistryManager),
        container.get(Database),
        container.get(redis.Redis),
        container.get(RateLimitMetrics),
        container.get(NotificationScheduler),
    )

    # Phase 2: Initialize infrastructure in parallel (independent subsystems)
    await asyncio.gather(
        initialize_event_schemas(schema_registry),
        init_beanie(database=database, document_models=ALL_DOCUMENTS),
        initialize_rate_limits(redis_client, settings, logger, rate_limit_metrics),
    )
    logger.info("Infrastructure initialized (schemas, beanie, rate limits)")

    # Phase 3: Start Kafka broker (subscribers begin consuming)
    await broker.start()
    logger.info("Kafka broker started — consumers active")

    try:
        yield
    finally:
        await broker.close()
        logger.info("Kafka broker stopped")
