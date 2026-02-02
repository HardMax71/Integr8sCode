import asyncio
import logging
import signal

from app.core.container import create_result_processor_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.result_processor.processor import ResultProcessor
from app.settings import Settings
from beanie import init_beanie


async def run_result_processor(settings: Settings) -> None:
    """Run the result processor."""

    container = create_result_processor_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting ResultProcessor with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Triggers consumer start via DI
    await container.get(ResultProcessor)

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("ResultProcessor started and running")

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Initiating graceful shutdown...")
        await container.close()

    logger.warning("ResultProcessor stopped")


def main() -> None:
    """Main entry point for result processor worker"""
    settings = Settings(override_path="config.result-processor.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting ResultProcessor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.RESULT_PROCESSOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for ResultProcessor Service")

    asyncio.run(run_result_processor(settings))


if __name__ == "__main__":
    main()
