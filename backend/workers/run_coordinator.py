import asyncio
import logging
import signal
from contextlib import AsyncExitStack

from app.core.container import create_coordinator_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.settings import Settings, get_settings
from beanie import init_beanie


async def run_coordinator(settings: Settings | None = None) -> None:
    """Run the execution coordinator service."""
    if settings is None:
        settings = get_settings()

    container = create_coordinator_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting ExecutionCoordinator with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    producer = await container.get(UnifiedProducer)
    coordinator = await container.get(ExecutionCoordinator)

    loop = asyncio.get_running_loop()

    async def shutdown() -> None:
        logger.info("Initiating graceful shutdown...")
        await coordinator.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    async with AsyncExitStack() as stack:
        stack.push_async_callback(container.close)
        await stack.enter_async_context(producer)
        await stack.enter_async_context(coordinator)

        while coordinator._running:
            await asyncio.sleep(60)
            status = await coordinator.get_status()
            logger.info(f"Coordinator status: {status}")


def main() -> None:
    """Main entry point for coordinator worker"""
    settings = get_settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting ExecutionCoordinator worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.EXECUTION_COORDINATOR,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for ExecutionCoordinator")

    asyncio.run(run_coordinator(settings))


if __name__ == "__main__":
    main()
