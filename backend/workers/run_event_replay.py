import asyncio
import signal

from app.core.container import create_event_replay_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.services.event_replay.replay_service import EventReplayService
from app.settings import Settings
from beanie import init_beanie


async def run_replay_service(settings: Settings) -> None:
    """Run the event replay service with DI-managed cleanup scheduler."""
    logger = setup_logger(settings.LOG_LEVEL)

    # Initialize Beanie with connection string (manages client internally)
    await init_beanie(connection_string=settings.MONGODB_URL, document_models=ALL_DOCUMENTS)
    logger.info("MongoDB initialized via Beanie")

    # Create DI container
    container = create_event_replay_container(settings)
    logger.info("Starting EventReplayService with DI container...")

    # Resolving EventReplayService starts the APScheduler cleanup scheduler
    # (via EventReplayWorkerProvider). Broker is started automatically by
    # BrokerProvider when first resolved.
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
