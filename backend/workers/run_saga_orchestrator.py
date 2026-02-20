import asyncio
from typing import Any

from app.core.container import create_saga_orchestrator_container
from app.core.logging import setup_logger
from app.db.docs import ALL_DOCUMENTS
from app.events.handlers import register_saga_subscriber
from app.services.saga import SagaOrchestrator
from app.settings import Settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = Settings(override_path="config.saga-orchestrator.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting Saga Orchestrator worker...")

    async def run() -> None:
        # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.DATABASE_NAME),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        # Create DI container
        container = create_saga_orchestrator_container(settings)

        # Get broker from DI
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Register subscriber and set up DI integration
        register_saga_subscriber(broker)
        setup_dishka(container, broker=broker, auto_inject=True)

        scheduler = AsyncIOScheduler()

        async def init_saga() -> None:
            orchestrator = await container.get(SagaOrchestrator)
            scheduler.add_job(
                orchestrator.check_timeouts,
                trigger="interval",
                seconds=30,
                id="saga_check_timeouts",
                max_instances=1,
                misfire_grace_time=60,
            )
            scheduler.add_job(
                orchestrator.try_schedule_from_queue,
                trigger="interval",
                seconds=10,
                id="saga_try_schedule",
                max_instances=1,
                misfire_grace_time=30,
            )
            scheduler.start()
            logger.info("SagaOrchestrator initialized (APScheduler: timeouts=30s, scheduling=10s)")

        async def shutdown() -> None:
            scheduler.shutdown(wait=False)
            await container.close()

        app = FastStream(broker, on_startup=[init_saga], on_shutdown=[shutdown])
        await app.run()
        logger.info("SagaOrchestrator shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
