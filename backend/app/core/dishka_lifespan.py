from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dishka import AsyncContainer
from dishka.integrations.faststream import setup_dishka as setup_dishka_faststream
from fastapi import FastAPI
from faststream.kafka import KafkaBroker

from app.core.tracing import init_tracing
from app.events.handlers import (
    register_notification_subscriber,
    register_sse_subscriber,
)
from app.services.notification_scheduler import NotificationScheduler
from app.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan with dishka dependency injection.

    Infrastructure init (Beanie, schemas, rate limits) is handled inside
    DI providers. Resolving NotificationScheduler cascades through the
    dependency graph and triggers all required initialisation.

    KafkaBroker is created via BrokerProvider. Subscriber registration,
    FastStream integration setup, and broker lifecycle (start/stop) are
    managed here.
    """
    container: AsyncContainer = app.state.dishka_container
    settings: Settings = app.state.settings
    logger = await container.get(logging.Logger)

    logger.info(
        "Starting application with dishka DI",
        extra={
            "project_name": settings.PROJECT_NAME,
            "environment": "test" if settings.TESTING else "production",
        },
    )

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

    # Get broker from DI (created by BrokerProvider)
    broker: KafkaBroker = await container.get(KafkaBroker)
    app.state.kafka_broker = broker

    # Register in-app Kafka subscribers
    register_sse_subscriber(broker, settings)
    register_notification_subscriber(broker, settings)
    logger.info("Kafka subscribers registered")

    # Set up FastStream DI integration
    setup_dishka_faststream(container, broker=broker, auto_inject=True)
    logger.info("FastStream DI integration configured")

    # Resolve NotificationScheduler — cascades init_beanie, schema registration,
    # and starts APScheduler via the DI provider graph.
    await container.get(NotificationScheduler)
    logger.info("Infrastructure initialized via DI providers")

    # Start Kafka broker (subscribers begin consuming)
    await broker.start()
    logger.info("Kafka broker started — consumers active")

    try:
        yield
    finally:
        await broker.close()
        logger.info("Kafka broker stopped")
