import asyncio

from app.core.container import create_saga_orchestrator_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.events.broker import create_broker
from app.events.handlers import register_saga_subscriber
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.saga import SagaOrchestrator
from app.settings import Settings
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = Settings(override_path="config.saga-orchestrator.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting Saga Orchestrator worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.SAGA_ORCHESTRATOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for Saga Orchestrator Service")

    # Create Kafka broker and register subscriber
    schema_registry = SchemaRegistryManager(settings, logger)
    broker = create_broker(settings, schema_registry, logger)
    register_saga_subscriber(broker, settings)

    # Create DI container with broker in context
    container = create_saga_orchestrator_container(settings, broker)
    setup_dishka(container, broker=broker, auto_inject=True)

    app = FastStream(broker)

    @app.on_startup
    async def startup() -> None:
        # Resolving SagaOrchestrator triggers Database init (via dependency)
        # and starts the APScheduler timeout checker (via SagaWorkerProvider)
        await container.get(SagaOrchestrator)
        logger.info("SagaOrchestrator infrastructure initialized")

    @app.on_shutdown
    async def shutdown() -> None:
        await container.close()
        logger.info("SagaOrchestrator shutdown complete")

    async def run() -> None:
        await app.run()

    asyncio.run(run())


if __name__ == "__main__":
    main()
