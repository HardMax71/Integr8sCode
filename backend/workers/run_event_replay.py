"""Event replay worker entrypoint - stateless replay service.

Provides event replay capability. DI container manages all lifecycle.
This service doesn't consume from Kafka - it's an HTTP-driven replay service.
"""

import asyncio
import logging

from app.core.container import create_event_replay_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.settings import Settings
from beanie import init_beanie


async def run_replay_service(settings: Settings) -> None:
    """Run the event replay service."""

    container = create_event_replay_container(settings)

    logger = await container.get(logging.Logger)
    logger.info("Starting EventReplayService with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    logger.info("Event replay service initialized and ready")

    # Service is HTTP-driven, wait for external shutdown
    await asyncio.Event().wait()

    await container.close()


def main() -> None:
    """Main entry point for event replay service"""
    settings = Settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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
