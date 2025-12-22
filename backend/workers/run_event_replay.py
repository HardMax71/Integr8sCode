import asyncio
import logging
from contextlib import AsyncExitStack

from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.repositories.replay_repository import ReplayRepository
from app.db.schema.schema_manager import SchemaManager
from app.events.core import ProducerConfig, UnifiedProducer
from app.events.event_store import create_event_store
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.event_replay.replay_service import EventReplayService
from app.settings import get_settings
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
    db_name = settings.DATABASE_NAME
    database = db_client[db_name]

    # Verify connection
    await db_client.admin.command("ping")
    logger.info(f"Connected to database: {db_name}")

    # Ensure DB schema
    await SchemaManager(database).apply_all()

    # Initialize services
    schema_registry = SchemaRegistryManager()
    producer_config = ProducerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
    )
    producer = UnifiedProducer(producer_config, schema_registry)

    # Create event store
    event_store = create_event_store(db=database, schema_registry=schema_registry)

    # Ensure schema (indexes) for this worker process
    schema_manager = SchemaManager(database)
    await schema_manager.apply_all()

    # Create repository
    replay_repository = ReplayRepository(database)

    # Create replay service
    replay_service = EventReplayService(
        repository=replay_repository,
        producer=producer,
        event_store=event_store
    )
    logger.info("Event replay service initialized")

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(producer)
        stack.callback(db_client.close)

        task = asyncio.create_task(cleanup_task(replay_service))
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

    asyncio.run(run_replay_service())


if __name__ == "__main__":
    main()
