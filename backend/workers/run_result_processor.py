"""
Result Processor Worker using FastStream.

This is the clean version:
- No asyncio.get_running_loop()
- No signal.SIGINT/SIGTERM handlers
- No create_task()
- No manual consumer loops
- No TaskGroup management

Everything is handled by FastStream + Dishka DI.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.logging import setup_logger
from app.core.providers import (
    BoundaryClientProvider,
    CoreServicesProvider,
    EventProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    RedisServicesProvider,
    RepositoryProvider,
    ResultProcessorProvider,
    SettingsProvider,
)
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.domain.events.typed import (
    DomainEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.faststream_middleware import IdempotencyMiddleware
from app.services.result_processor.processor_logic import ProcessorLogic
from app.settings import Settings
from beanie import init_beanie
from dishka import make_async_container
from dishka.integrations.faststream import FromDishka, setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo.asynchronous.mongo_client import AsyncMongoClient


def main() -> None:
    """
    Entry point - minimal boilerplate.

    FastStream handles:
    - Signal handling (SIGINT/SIGTERM)
    - Consumer loop
    - Graceful shutdown
    """
    settings = Settings()

    # Setup logging
    logger = setup_logger(settings.LOG_LEVEL)
    logger.info("Starting ResultProcessor (FastStream)...")

    # Setup tracing
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.RESULT_PROCESSOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )

    # Create DI container with all providers
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        CoreServicesProvider(),
        BoundaryClientProvider(),
        RedisServicesProvider(),
        MetricsProvider(),
        EventProvider(),
        MessagingProvider(),
        RepositoryProvider(),
        ResultProcessorProvider(),
        context={Settings: settings},
    )

    # Build topic list and group ID from config
    topics = [
        f"{settings.KAFKA_TOPIC_PREFIX}{t}"
        for t in CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.RESULT_PROCESSOR]
    ]
    group_id = f"{GroupId.RESULT_PROCESSOR}.{settings.KAFKA_GROUP_SUFFIX}"

    # Create broker
    broker = KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
    )

    # Create lifespan for infrastructure initialization
    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        """Initialize infrastructure before app starts."""
        app_logger = await container.get(logging.Logger)
        app_logger.info("ResultProcessor starting...")

        # Initialize MongoDB + Beanie
        mongo_client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
            settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        await init_beanie(database=mongo_client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

        # Resolve schema registry (initialization handled by provider)
        schema_registry = await container.get(SchemaRegistryManager)

        # Resolve Kafka producer (lifecycle managed by DI - BoundaryClientProvider starts it)
        await container.get(UnifiedProducer)
        app_logger.info("Kafka producer ready")

        # Decoder: Avro bytes → typed DomainEvent
        async def decode_avro(body: bytes) -> DomainEvent:
            return await schema_registry.deserialize_event(body, "result_processor")

        # Create subscriber with Avro decoder
        subscriber = broker.subscriber(
            *topics,
            group_id=group_id,
            auto_commit=False,
            decoder=decode_avro,
        )

        # Route by event_type header (producer sets this, Kafka stores as bytes)
        @subscriber(filter=lambda msg: msg.headers.get("event_type") == EventType.EXECUTION_COMPLETED.encode())
        async def handle_completed(
            event: ExecutionCompletedEvent,
            logic: FromDishka[ProcessorLogic],
        ) -> None:
            await logic._handle_completed(event)

        @subscriber(filter=lambda msg: msg.headers.get("event_type") == EventType.EXECUTION_FAILED.encode())
        async def handle_failed(
            event: ExecutionFailedEvent,
            logic: FromDishka[ProcessorLogic],
        ) -> None:
            await logic._handle_failed(event)

        @subscriber(filter=lambda msg: msg.headers.get("event_type") == EventType.EXECUTION_TIMEOUT.encode())
        async def handle_timeout(
            event: ExecutionTimeoutEvent,
            logic: FromDishka[ProcessorLogic],
        ) -> None:
            await logic._handle_timeout(event)

        # Default handler for unmatched events (prevents message loss)
        @subscriber()
        async def handle_other(event: DomainEvent) -> None:
            pass

        app_logger.info("Infrastructure initialized, starting event processing...")

        try:
            yield
        finally:
            app_logger.info("ResultProcessor shutting down...")
            await mongo_client.close()
            await container.close()
            app_logger.info("ResultProcessor shutdown complete")

    # Create FastStream app
    app = FastStream(broker, lifespan=lifespan)

    # Setup Dishka integration for automatic DI in handlers
    setup_dishka(container=container, app=app, auto_inject=True)

    # Add idempotency middleware (appends to end = most inner, runs after Dishka)
    broker.add_middleware(IdempotencyMiddleware)

    # Run! FastStream handles signal handling, consumer loops, graceful shutdown
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
