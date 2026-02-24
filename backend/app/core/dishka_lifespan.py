from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka import AsyncContainer
from dishka.integrations.faststream import setup_dishka as setup_dishka_faststream
from fastapi import FastAPI
from faststream.kafka import KafkaBroker
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pymongo import AsyncMongoClient

from app.core.tracing import Tracer
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

    DI container is created in create_app() and middleware is set up there.
    init_beanie() is called here BEFORE any providers are resolved, so that
    Beanie document classes are initialized before repositories use them.

    KafkaBroker lifecycle (start/stop) is managed here explicitly.
    Subscriber registration and FastStream integration are set up here.
    """
    settings: Settings = app.state.settings
    container: AsyncContainer = app.state.dishka_container
    logger: structlog.stdlib.BoundLogger = await container.get(structlog.stdlib.BoundLogger)

    # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes).
    # Use URL database first and fall back to configured DATABASE_NAME so runtime
    # and auxiliary scripts resolve the same DB consistently.
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
    database = client.get_default_database(default=settings.DATABASE_NAME)
    await init_beanie(database=database, document_models=ALL_DOCUMENTS)
    logger.info("MongoDB initialized via Beanie")

    await container.get(Tracer)
    FastAPIInstrumentor().instrument_app(
        app, tracer_provider=trace.get_tracer_provider(), excluded_urls="health,metrics,docs,openapi.json",
    )
    logger.info("FastAPI OpenTelemetry instrumentation applied")

    logger.info(
        "Starting application with dishka DI",
        project_name=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
    )

    # Get unstarted broker from DI (BrokerProvider yields without starting)
    broker: KafkaBroker = await container.get(KafkaBroker)

    # Register subscribers BEFORE broker.start() - FastStream requirement
    register_sse_subscriber(broker, settings)
    register_notification_subscriber(broker)
    logger.info("Kafka subscribers registered")

    # Set up FastStream DI integration (must be before start per Dishka docs)
    setup_dishka_faststream(container, broker=broker, auto_inject=True)
    logger.info("FastStream DI integration configured")

    # Now start the broker
    await broker.start()
    logger.info("Kafka broker started")

    # Set up APScheduler for NotificationScheduler
    notification_scheduler: NotificationScheduler = await container.get(NotificationScheduler)
    notification_apscheduler = AsyncIOScheduler()
    notification_apscheduler.add_job(
        notification_scheduler.process_due_notifications,
        trigger="interval",
        seconds=15,
        id="process_due_notifications",
        max_instances=1,
        misfire_grace_time=60,
    )
    notification_apscheduler.start()
    logger.info("NotificationScheduler started (APScheduler interval=15s)")

    try:
        yield
    finally:
        notification_apscheduler.shutdown(wait=False)
        logger.info("NotificationScheduler stopped")
        await broker.stop()
        logger.info("Kafka broker stopped")
        await container.close()
        logger.info("DI container closed")
