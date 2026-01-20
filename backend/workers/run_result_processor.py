import asyncio
import logging
import signal

from app.core.container import create_result_processor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import Settings
from beanie import init_beanie
from pymongo.asynchronous.mongo_client import AsyncMongoClient


async def run_result_processor(settings: Settings) -> None:
    """Run the result processor service."""

    db_client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    await init_beanie(database=db_client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

    container = create_result_processor_container(settings)
    logger = await container.get(logging.Logger)

    consumer = await container.get(IdempotentConsumerWrapper)

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("ResultProcessor consumer initialized, starting run...")

    try:
        # Run consumer until shutdown signal
        run_task = asyncio.create_task(consumer.run())
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
        await db_client.close()


def main() -> None:
    """Main entry point for result processor worker"""
    settings = Settings()

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
