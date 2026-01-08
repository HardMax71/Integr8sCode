import asyncio
import logging
from contextlib import AsyncExitStack

from app.core.container import create_event_replay_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.events.core import UnifiedProducer
from app.services.event_replay.replay_service import EventReplayService
from app.settings import Settings, get_settings


async def cleanup_task(replay_service: EventReplayService, logger: logging.Logger, interval_hours: int = 6) -> None:
    """Periodically clean up old replay sessions"""
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            removed = await replay_service.cleanup_old_sessions(older_than_hours=48)
            logger.info(f"Cleaned up {removed} old replay sessions")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


async def run_replay_service(settings: Settings | None = None) -> None:
    """Run the event replay service with cleanup task."""
    if settings is None:
        settings = get_settings()

    container = create_event_replay_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting EventReplayService with DI container...")

    producer = await container.get(UnifiedProducer)
    replay_service = await container.get(EventReplayService)

    logger.info("Event replay service initialized")

    async with AsyncExitStack() as stack:
        stack.push_async_callback(container.close)
        await stack.enter_async_context(producer)

        task = asyncio.create_task(cleanup_task(replay_service, logger))

        async def _cancel_task() -> None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        stack.push_async_callback(_cancel_task)

        await asyncio.Event().wait()


def main() -> None:
    """Main entry point for event replay service"""
    settings = get_settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting Event Replay Service...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name="event-replay",
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for Event Replay Service")

    asyncio.run(run_replay_service(settings))


if __name__ == "__main__":
    main()
