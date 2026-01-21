"""
Saga Orchestrator Worker using FastStream.

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
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.providers import (
    BoundaryClientProvider,
    DatabaseProvider,
    EventProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    RedisServicesProvider,
    RepositoryProvider,
    SagaOrchestratorProvider,
    SettingsProvider,
)
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.domain.events.typed import DomainEvent
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.faststream_middleware import IdempotencyMiddleware
from app.services.saga.saga_logic import SagaLogic
from app.settings import Settings
from dishka import make_async_container
from dishka.integrations.faststream import FromDishka, setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker


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
    logger.info("Starting SagaOrchestrator (FastStream)...")

    # Setup tracing
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.SAGA_ORCHESTRATOR,
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
        BoundaryClientProvider(),
        RedisServicesProvider(),
        DatabaseProvider(),
        MetricsProvider(),
        EventProvider(),
        MessagingProvider(),
        RepositoryProvider(),
        SagaOrchestratorProvider(),
        context={Settings: settings},
    )

    # We need to determine topics dynamically based on registered sagas
    # This will be done in lifespan after SagaLogic is initialized

    # Create broker
    broker = KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
    )

    # Track timeout checking state for opportunistic checking
    timeout_check_state = {"last_check": 0.0, "interval": 30.0}

    # Create lifespan for infrastructure initialization
    @asynccontextmanager
    async def lifespan(app: FastStream) -> AsyncIterator[None]:
        """Initialize infrastructure before app starts."""
        app_logger = await container.get(logging.Logger)
        app_logger.info("SagaOrchestrator starting...")

        # Resolve dependencies (initialization handled by providers)
        await container.get(Database)  # Triggers init_beanie via DatabaseProvider
        schema_registry = await container.get(SchemaRegistryManager)  # Triggers initialize_schemas

        # Resolve Kafka producer (lifecycle managed by DI - BoundaryClientProvider starts it)
        await container.get(UnifiedProducer)
        app_logger.info("Kafka producer ready")

        # Get saga logic to determine topics
        logic = await container.get(SagaLogic)
        trigger_topics = logic.get_trigger_topics()

        if not trigger_topics:
            app_logger.warning("No saga triggers configured, shutting down")
            yield
            await container.close()
            return

        # Build topic list with prefix
        topics = [f"{settings.KAFKA_TOPIC_PREFIX}{t}" for t in trigger_topics]
        group_id = f"{GroupId.SAGA_ORCHESTRATOR}.{settings.KAFKA_GROUP_SUFFIX}"

        # Decoder: Avro bytes → typed DomainEvent
        async def decode_avro(body: bytes) -> DomainEvent:
            return await schema_registry.deserialize_event(body, "saga_orchestrator")

        # Register handler dynamically after determining topics
        # Saga orchestrator uses single handler - routing is internal to SagaLogic
        @broker.subscriber(
            *topics,
            group_id=group_id,
            auto_commit=False,
            decoder=decode_avro,
        )
        async def handle_saga_event(
            event: DomainEvent,
            saga_logic: FromDishka[SagaLogic],
        ) -> None:
            """
            Handle saga trigger events.

            Dependencies are automatically injected via Dishka.
            Routing is handled internally by SagaLogic based on saga configuration.
            """
            # Handle the event through saga logic (internal routing)
            await saga_logic.handle_event(event)

            # Opportunistic timeout check (replaces background loop)
            now = time.monotonic()
            if now - timeout_check_state["last_check"] >= timeout_check_state["interval"]:
                await saga_logic.check_timeouts_once()
                timeout_check_state["last_check"] = now

        app_logger.info(f"Subscribing to topics: {topics}")
        app_logger.info("Infrastructure initialized, starting event processing...")

        try:
            yield
        finally:
            app_logger.info("SagaOrchestrator shutting down...")
            # Container close stops Kafka producer via DI provider
            await container.close()
            app_logger.info("SagaOrchestrator shutdown complete")

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
