import asyncio
from typing import Any

from app.core.container import create_dlq_processor_container
from app.core.logging import setup_logger
from app.db.docs import ALL_DOCUMENTS
from app.dlq.manager import DLQManager
from app.events.handlers import register_dlq_subscriber
from app.settings import Settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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

        scheduler = AsyncIOScheduler()

        async def init_dlq() -> None:
            manager = await container.get(DLQManager)
            scheduler.add_job(
                manager.process_monitoring_cycle,
                trigger="interval",
                seconds=10,
                id="dlq_monitor_retries",
                max_instances=1,
                misfire_grace_time=60,
            )
            scheduler.start()
            logger.info("DLQ Processor initialized (APScheduler interval=10s)")

        async def shutdown() -> None:
            scheduler.shutdown(wait=False)
            await container.close()

        app = FastStream(broker, on_startup=[init_dlq], on_shutdown=[shutdown])
        await app.run()
        logger.info("DLQ Processor shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
