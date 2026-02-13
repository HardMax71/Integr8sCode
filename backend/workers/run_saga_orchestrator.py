import asyncio
from typing import Any

from app.core.container import create_saga_orchestrator_container
from app.core.logging import setup_logger
from app.db.docs import ALL_DOCUMENTS
from app.events.handlers import register_saga_subscriber
from app.services.saga import SagaOrchestrator
from app.settings import Settings
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
        register_saga_subscriber(broker, settings)
        setup_dishka(container, broker=broker, auto_inject=True)

        # Resolving SagaOrchestrator starts APScheduler timeout checker (via provider)
        async def init_saga() -> None:
            await container.get(SagaOrchestrator)
            logger.info("SagaOrchestrator initialized")

        app = FastStream(broker, on_startup=[init_saga], on_shutdown=[container.close])
        await app.run()
        logger.info("SagaOrchestrator shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
