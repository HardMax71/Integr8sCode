import asyncio
from typing import Any

from app.core.container import create_event_replay_container
from app.core.logging import setup_logger
from app.db.docs import ALL_DOCUMENTS
from app.services.event_replay import EventReplayService
from app.settings import Settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


def main() -> None:
    """Main entry point for event replay service"""
    settings = Settings(override_path="config.event-replay.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting Event Replay Service...")

    async def run() -> None:
        # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.DATABASE_NAME),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        container = create_event_replay_container(settings)
        broker: KafkaBroker = await container.get(KafkaBroker)
        setup_dishka(container, broker=broker, auto_inject=True)

        scheduler = AsyncIOScheduler()

        async def init_replay() -> None:
            service = await container.get(EventReplayService)
            scheduler.add_job(
                service.cleanup_old_sessions,
                trigger="interval",
                hours=6,
                kwargs={"older_than_hours": 48},
                id="replay_cleanup_old_sessions",
                max_instances=1,
                misfire_grace_time=300,
            )
            scheduler.start()
            logger.info("Event replay service initialized (APScheduler interval=6h)")

        async def shutdown() -> None:
            scheduler.shutdown(wait=False)
            await container.close()

        app = FastStream(broker, on_startup=[init_replay], on_shutdown=[shutdown])
        await app.run()
        logger.info("EventReplayService shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
