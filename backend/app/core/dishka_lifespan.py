from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from beanie import init_beanie
from dishka.integrations.fastapi import setup_dishka as setup_dishka_fastapi
from dishka.integrations.faststream import setup_dishka as setup_dishka_faststream
from fastapi import FastAPI
from faststream.kafka import KafkaBroker

from app.core.container import create_app_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
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

    Infrastructure bootstrapping (init_beanie) happens here BEFORE the DI
    container is created. Beanie manages the MongoDB connection internally.

    KafkaBroker lifecycle (start/stop) is managed by BrokerProvider.
    Subscriber registration and FastStream integration are set up here.
    """
    settings: Settings = app.state.settings
    logger = setup_logger(settings.LOG_LEVEL)

    # Initialize Beanie with connection string (manages client internally)
    await init_beanie(connection_string=settings.MONGODB_URL, document_models=ALL_DOCUMENTS)
    logger.info("MongoDB initialized via Beanie")

    # Create DI container
    container = create_app_container(settings)
    setup_dishka_fastapi(container, app)
    logger.info("DI container created")

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

    # Get broker from DI (BrokerProvider starts it automatically)
    broker: KafkaBroker = await container.get(KafkaBroker)
    app.state.kafka_broker = broker

    # Register in-app Kafka subscribers (works on already-started broker)
    register_sse_subscriber(broker, settings)
    register_notification_subscriber(broker, settings)
    logger.info("Kafka subscribers registered")

    # Set up FastStream DI integration
    setup_dishka_faststream(container, broker=broker, auto_inject=True)
    logger.info("FastStream DI integration configured")

    # Resolve NotificationScheduler — starts APScheduler via DI provider graph.
    # (init_beanie already completed above, before container creation)
    await container.get(NotificationScheduler)
    logger.info("NotificationScheduler started")

    try:
        yield
    finally:
        # Container close triggers BrokerProvider cleanup (closes broker)
        # and all other async generators in providers
        await container.close()
        logger.info("DI container closed")
