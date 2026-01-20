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
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.services.saga.saga_logic import SagaLogic
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

    consumer = await container.get(IdempotentConsumerWrapper | None)
    logic = await container.get(SagaLogic)

    # Handle case where no sagas have triggers
    if consumer is None:
        logger.warning("No consumer provided (no saga triggers), exiting")
        await container.close()
        return

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info(f"SagaOrchestrator initialized for saga: {logic.config.name}, starting run...")

    async def run_orchestrator_tasks() -> None:
        """Run consumer and timeout checker using TaskGroup."""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(consumer.run())
            tg.create_task(logic.check_timeouts_loop())

    try:
        # Run orchestrator until shutdown signal
        run_task = asyncio.create_task(run_orchestrator_tasks())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            [run_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    finally:
        logger.info("Initiating graceful shutdown...")
        await container.close()

    logger.warning("Saga orchestrator stopped")


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = Settings()

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
