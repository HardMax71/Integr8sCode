import asyncio
import signal
from typing import Any

from app.core.container import create_event_replay_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.services.event_replay import EventReplayService
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


async def run_replay_service(settings: Settings) -> None:
    """Run the event replay service with DI-managed cleanup scheduler."""
    logger = setup_logger(settings.LOG_LEVEL)

    # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
    await init_beanie(
        database=client.get_default_database(default=settings.DATABASE_NAME),
        document_models=ALL_DOCUMENTS,
    )
    logger.info("MongoDB initialized via Beanie")

    # Create DI container
    container = create_event_replay_container(settings)
    logger.info("Starting EventReplayService with DI container...")

    # Get broker, setup DI, start (no subscribers - this worker only publishes)
    broker: KafkaBroker = await container.get(KafkaBroker)
    setup_dishka(container, broker=broker, auto_inject=True)
    await broker.start()
    logger.info("Kafka broker started")

    # Resolving EventReplayService starts the APScheduler cleanup scheduler
    # (via EventReplayWorkerProvider).
    await container.get(EventReplayService)
    logger.info("Event replay service initialized")

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    try:
        await shutdown_event.wait()
    finally:
        logger.info("Initiating graceful shutdown...")
        await container.close()


def main() -> None:
    """Main entry point for event replay service"""
    settings = Settings(override_path="config.event-replay.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting Event Replay Service...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name="event-replay",
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for Event Replay Service")

    asyncio.run(run_replay_service(settings))


if __name__ == "__main__":
    main()
