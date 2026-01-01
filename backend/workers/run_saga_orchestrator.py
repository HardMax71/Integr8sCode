import asyncio
import logging
from contextlib import AsyncExitStack

from app.core.container import create_saga_orchestrator_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.saga import SagaOrchestrator
from app.settings import Settings, get_settings
from beanie import init_beanie


async def run_saga_orchestrator(settings: Settings | None = None) -> None:
    """Run the saga orchestrator."""
    if settings is None:
        settings = get_settings()

    container = create_saga_orchestrator_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting SagaOrchestrator with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    producer = await container.get(UnifiedProducer)
    orchestrator = await container.get(SagaOrchestrator)

    async with AsyncExitStack() as stack:
        stack.push_async_callback(container.close)
        await stack.enter_async_context(producer)
        await stack.enter_async_context(orchestrator)

        logger.info("Saga orchestrator started and running")

        while orchestrator.is_running:
            await asyncio.sleep(60)
            logger.info("Saga orchestrator is running...")

        logger.warning("Saga orchestrator stopped")


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = get_settings()

    # Setup logging
    logger = setup_logger(settings.LOG_LEVEL)

    # Configure root logger for worker
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting Saga Orchestrator worker...")

    # Initialize tracing
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.SAGA_ORCHESTRATOR,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for Saga Orchestrator Service")

    asyncio.run(run_saga_orchestrator())


if __name__ == "__main__":
    main()
