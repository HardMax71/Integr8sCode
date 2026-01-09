import asyncio
import logging
import signal
from contextlib import AsyncExitStack

from app.core.container import create_result_processor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.db.repositories.execution_repository import ExecutionRepository
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency import IdempotencyManager
from app.services.result_processor.processor import ProcessingState, ResultProcessor
from app.settings import Settings, get_settings
from beanie import init_beanie
from pymongo.asynchronous.mongo_client import AsyncMongoClient


async def run_result_processor(settings: Settings | None = None) -> None:
    if settings is None:
        settings = get_settings()

    db_client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    await init_beanie(database=db_client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

    container = create_result_processor_container(settings)
    producer = await container.get(UnifiedProducer)
    schema_registry = await container.get(SchemaRegistryManager)
    idempotency_manager = await container.get(IdempotencyManager)
    execution_repo = await container.get(ExecutionRepository)
    logger = await container.get(logging.Logger)
    logger.info(f"Beanie ODM initialized with {len(ALL_DOCUMENTS)} document models")

    # ResultProcessor is manually created (not from DI), so we own its lifecycle
    processor = ResultProcessor(
        execution_repo=execution_repo,
        producer=producer,
        schema_registry=schema_registry,
        settings=settings,
        idempotency_manager=idempotency_manager,
        logger=logger,
    )

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    # We own the processor, so we use async with to manage its lifecycle
    async with AsyncExitStack() as stack:
        stack.callback(db_client.close)
        stack.push_async_callback(container.close)
        await stack.enter_async_context(processor)

        logger.info("ResultProcessor started and running")

        # Wait for shutdown signal or service to stop
        while processor._state == ProcessingState.PROCESSING and not shutdown_event.is_set():
            await asyncio.sleep(60)
            status = await processor.get_status()
            logger.info(f"ResultProcessor status: {status}")

        logger.info("Initiating graceful shutdown...")


def main() -> None:
    """Main entry point for result processor worker"""
    settings = get_settings()

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
