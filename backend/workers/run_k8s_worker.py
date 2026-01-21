"""
Kubernetes Worker using FastStream.

This is the clean version:
- No asyncio.get_running_loop()
- No signal.SIGINT/SIGTERM handlers
- No create_task() at worker level
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
    EventProvider,
    K8sWorkerProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    RedisServicesProvider,
    SettingsProvider,
)
from app.core.tracing import init_tracing
from app.domain.enums.events import EventType
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.domain.events.typed import (
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    DomainEvent,
)
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency.faststream_middleware import IdempotencyMiddleware
from app.services.k8s_worker.worker_logic import K8sWorkerLogic
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
    logger.info("Starting KubernetesWorker (FastStream)...")

    # Setup tracing
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.K8S_WORKER,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )

    # Create DI container (no DatabaseProvider/RepositoryProvider - K8s worker doesn't use MongoDB)
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BoundaryClientProvider(),
        RedisServicesProvider(),
        MetricsProvider(),
        EventProvider(),
        MessagingProvider(),
        K8sWorkerProvider(),
        context={Settings: settings},
    )

    # Build topic list and group ID from config
    topics = [
        f"{settings.KAFKA_TOPIC_PREFIX}{t}"
        for t in CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.K8S_WORKER]
    ]
    group_id = f"{GroupId.K8S_WORKER}.{settings.KAFKA_GROUP_SUFFIX}"

    # Create broker
    broker = KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
    )

    # Create lifespan for infrastructure initialization
    @asynccontextmanager
    async def lifespan(app: FastStream) -> AsyncIterator[None]:
        """Initialize infrastructure before app starts."""
        app_logger = await container.get(logging.Logger)
        app_logger.info("KubernetesWorker starting...")

        # Get worker logic - triggers full dependency chain:
        # K8sWorkerLogic -> UnifiedProducer -> SchemaRegistryManager (init)
        logic = await container.get(K8sWorkerLogic)

        # Get schema registry for decoder (already initialized via chain above)
        schema_registry = await container.get(SchemaRegistryManager)
        await logic.ensure_image_pre_puller_daemonset()

        # Decoder: Avro bytes → typed DomainEvent
        async def decode_avro(body: bytes) -> DomainEvent:
            return await schema_registry.deserialize_event(body, "k8s_worker")

        # Create subscriber with Avro decoder
        subscriber = broker.subscriber(
            *topics,
            group_id=group_id,
            auto_commit=False,
            decoder=decode_avro,
        )

        # Route by event_type header (producer sets this, Kafka stores as bytes)
        @subscriber(filter=lambda msg: msg.headers.get("event_type") == EventType.CREATE_POD_COMMAND.encode())
        async def handle_create_pod_command(
            event: CreatePodCommandEvent,
            worker_logic: FromDishka[K8sWorkerLogic],
        ) -> None:
            await worker_logic.handle_create_pod_command(event)

        @subscriber(filter=lambda msg: msg.headers.get("event_type") == EventType.DELETE_POD_COMMAND.encode())
        async def handle_delete_pod_command(
            event: DeletePodCommandEvent,
            worker_logic: FromDishka[K8sWorkerLogic],
        ) -> None:
            await worker_logic.handle_delete_pod_command(event)

        # Default handler for unmatched events (prevents message loss)
        @subscriber()
        async def handle_other(event: DomainEvent) -> None:
            pass

        app_logger.info("Infrastructure initialized, starting event processing...")

        try:
            yield
        finally:
            # Graceful shutdown: wait for active pod creations
            app_logger.info("KubernetesWorker shutting down...")
            await logic.wait_for_active_creations()
            # Container close stops Kafka producer via DI provider
            await container.close()
            app_logger.info("KubernetesWorker shutdown complete")

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
