import asyncio
import logging
import signal

from app.core.container import create_saga_orchestrator_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.saga import SagaOrchestrator
from app.settings import Settings
from beanie import init_beanie


async def run_saga_orchestrator(settings: Settings) -> None:
    """Run the saga orchestrator."""

    container = create_saga_orchestrator_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting SagaOrchestrator with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Services are already started by the DI container providers
    orchestrator = await container.get(SagaOrchestrator)

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("Saga orchestrator started and running")

    try:
        # Wait for shutdown signal or service to stop
        while orchestrator.is_running and not shutdown_event.is_set():
            await asyncio.sleep(1)
    finally:
        # Container cleanup stops everything
        logger.info("Initiating graceful shutdown...")
        await container.close()

    logger.warning("Saga orchestrator stopped")


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = Settings(override_path="config.saga-orchestrator.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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

    asyncio.run(run_saga_orchestrator(settings))


if __name__ == "__main__":
    main()
