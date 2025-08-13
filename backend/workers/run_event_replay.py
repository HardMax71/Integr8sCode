"""Run Event Replay CLI as a standalone service"""

import asyncio
import logging

from app.config import get_settings
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.mongodb import DatabaseManager
from app.services.event_replay import get_replay_service
from app.services.event_replay.replay_service import EventReplayServiceSingleton


async def cleanup_task(interval_hours: int = 6) -> None:
    """Periodically clean up old replay sessions"""
    logger = logging.getLogger(__name__)
    replay_service = await get_replay_service()

    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)  # Convert hours to seconds
            removed = await replay_service.cleanup_old_sessions(older_than_hours=48)
            logger.info(f"Cleaned up {removed} old replay sessions")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


async def run_replay_service() -> None:
    """Run the event replay service with cleanup task"""
    logger = logging.getLogger(__name__)

    # Get settings
    settings = get_settings()

    # Create and set database manager
    db_manager = DatabaseManager(settings)
    await db_manager.connect_to_database()
    EventReplayServiceSingleton.set_database_manager(db_manager)

    # Initialize replay service
    _ = await get_replay_service()
    logger.info("Event replay service initialized")

    # Start cleanup task
    cleanup = asyncio.create_task(cleanup_task())

    try:
        # Keep service running
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("Replay service shutting down...")
        cleanup.cancel()
        try:
            await cleanup
        except asyncio.CancelledError:
            pass
    finally:
        await db_manager.close_database_connection()


def main() -> None:
    """Main entry point for event replay service"""
    # Setup logging
    setup_logger()

    # Configure root logger for worker
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting Event Replay Service...")

    # Initialize tracing
    settings = get_settings()
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name="event-replay",
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE
        )
        logger.info("Tracing initialized for Event Replay Service")

    try:
        # Run service
        asyncio.run(run_replay_service())
    except KeyboardInterrupt:
        logger.info("Event replay service interrupted by user")
    except Exception as e:
        logger.error(f"Event replay service failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
