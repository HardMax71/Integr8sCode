import asyncio
import logging

from app.config import get_settings
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.events.core.consumer_group_names import GroupId
from app.events.core.producer import create_unified_producer
from app.events.schema.schema_registry import create_schema_registry_manager, initialize_event_schemas
from app.services.saga.saga_orchestrator import create_saga_orchestrator
from motor.motor_asyncio import AsyncIOMotorClient


async def run_saga_orchestrator() -> None:
    """Run the saga orchestrator"""
    # Get settings
    settings = get_settings()
    logger = logging.getLogger(__name__)

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
    
    # Initialize schema registry
    logger.info("Initializing schema registry...")
    schema_registry_manager = create_schema_registry_manager()
    await initialize_event_schemas(schema_registry_manager)
    
    # Initialize Kafka producer
    logger.info("Initializing Kafka producer...")
    producer = create_unified_producer(schema_registry_manager=schema_registry_manager)
    await producer.start()
    
    # Initialize event store
    logger.info("Initializing event store...")
    from app.events.store.event_store import create_event_store
    event_store = create_event_store(
        db=database,
        ttl_days=90
    )
    await event_store.initialize()
    
    # Create saga orchestrator
    saga_orchestrator = create_saga_orchestrator(
        database=database,
        producer=producer,
        schema_registry_manager=schema_registry_manager,
        event_store=event_store
    )

    # Start the orchestrator
    await saga_orchestrator.start()

    logger.info("Saga orchestrator started and running")

    try:
        # Keep running
        while True:
            await asyncio.sleep(60)

            # Log status periodically
            if saga_orchestrator.is_running:
                logger.info("Saga orchestrator is running...")
            else:
                logger.warning("Saga orchestrator stopped unexpectedly")
                break

    except asyncio.CancelledError:
        logger.info("Saga orchestrator cancelled")
    finally:
        logger.info("Shutting down saga orchestrator...")
        await saga_orchestrator.stop()
        await producer.stop()
        db_client.close()
        logger.info("Saga orchestrator shutdown complete")


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    # Setup logging
    setup_logger()

    # Configure root logger for worker
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting Saga Orchestrator worker...")

    # Initialize tracing
    settings = get_settings()
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.SAGA_ORCHESTRATOR,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE
        )
        logger.info("Tracing initialized for Saga Orchestrator Service")

    try:
        # Run orchestrator
        asyncio.run(run_saga_orchestrator())
    except KeyboardInterrupt:
        logger.info("Saga orchestrator worker interrupted by user")
    except Exception as e:
        logger.error(f"Saga orchestrator worker failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
