import asyncio
import logging

from app.config import get_settings
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.events.core.producer import create_unified_producer
from app.events.store.event_store import create_event_store
from app.services.event_replay.replay_service import EventReplayService
from motor.motor_asyncio import AsyncIOMotorClient


async def cleanup_task(replay_service: EventReplayService, interval_hours: int = 6) -> None:
    """Periodically clean up old replay sessions"""
    logger = logging.getLogger(__name__)

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

    # Create database connection
    db_client: AsyncIOMotorClient = AsyncIOMotorClient(
        settings.MONGODB_URL,
        tz_aware=True,
        serverSelectionTimeoutMS=5000
    )
    db_name = settings.PROJECT_NAME + "_test" if settings.TESTING else settings.PROJECT_NAME
    database = db_client[db_name]

    # Verify connection
    await db_client.admin.command("ping")
    logger.info(f"Connected to database: {db_name}")

    # Initialize services
    producer = create_unified_producer()
    await producer.start()
    
    # Create event store
    event_store = create_event_store(database)
    await event_store.initialize()
    
    # Create replay service
    replay_service = EventReplayService(
        database=database,
        producer=producer,
        event_store=event_store
    )
    await replay_service.initialize_indexes()
    logger.info("Event replay service initialized")

    # Start cleanup task
    cleanup = asyncio.create_task(cleanup_task(replay_service))

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
        await producer.stop()
        db_client.close()


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
