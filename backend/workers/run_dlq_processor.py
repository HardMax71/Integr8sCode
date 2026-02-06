import asyncio
from typing import Any

from app.core.container import create_dlq_processor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.dlq.manager import DLQManager
from app.domain.enums.kafka import GroupId
from app.events.handlers import register_dlq_subscriber
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


def main() -> None:
    """Main entry point for DLQ processor worker."""
    settings = Settings(override_path="config.dlq-processor.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting DLQ Processor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.DLQ_MANAGER,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for DLQ Processor")

    async def run() -> None:
        # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.DATABASE_NAME),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        # Create DI container
        container = create_dlq_processor_container(settings)

        # Get broker from DI
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Register DLQ subscriber and set up DI integration
        register_dlq_subscriber(broker, settings)
        setup_dishka(container, broker=broker, auto_inject=True)

        # Resolving DLQManager starts APScheduler retry monitor (via provider)
        async def init_dlq() -> None:
            await container.get(DLQManager)
            logger.info("DLQ Processor initialized")

        app = FastStream(broker, on_startup=[init_dlq], on_shutdown=[container.close])
        await app.run()
        logger.info("DLQ Processor shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
