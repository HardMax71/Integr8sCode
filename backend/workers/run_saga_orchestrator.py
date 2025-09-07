import asyncio
import logging

from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.db.schema.schema_manager import SchemaManager
from app.domain.enums.kafka import GroupId
from app.domain.saga.models import SagaConfig
from app.events.core.producer import ProducerConfig, UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.idempotency import create_idempotency_manager
from app.services.saga.saga_orchestrator import create_saga_orchestrator
from app.settings import get_settings
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

    # Ensure DB schema (indexes/validators)
    await SchemaManager(database).apply_all()

    # Initialize schema registry
    logger.info("Initializing schema registry...")
    schema_registry_manager = SchemaRegistryManager()
    await schema_registry_manager.initialize_schemas()

    # Initialize Kafka producer
    logger.info("Initializing Kafka producer...")
    producer_config = ProducerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
    )
    producer = UnifiedProducer(producer_config, schema_registry_manager)
    await producer.start()

    # Create event store (schema ensured separately)
    logger.info("Creating event store...")
    from app.events.event_store import create_event_store
    event_store = create_event_store(
        db=database,
        schema_registry=schema_registry_manager,
        ttl_days=90
    )

    # Create repository and idempotency manager
    saga_repository = SagaRepository(database)
    idempotency_manager = create_idempotency_manager(database)
    resource_allocation_repository = ResourceAllocationRepository(database)

    # Create saga orchestrator
    saga_config = SagaConfig(
        name="main-orchestrator",
        timeout_seconds=300,
        max_retries=3,
        retry_delay_seconds=5,
        enable_compensation=True,
        store_events=True,
        publish_commands=True,
    )

    saga_orchestrator = create_saga_orchestrator(
        saga_repository=saga_repository,
        producer=producer,
        event_store=event_store,
        idempotency_manager=idempotency_manager,
        resource_allocation_repository=resource_allocation_repository,
        config=saga_config,
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
