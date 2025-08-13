"""Run Saga Orchestrator as a standalone worker service"""

import asyncio
import logging

from app.config import get_settings
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.mongodb import DatabaseManager
from app.events.core.consumer_group_names import GroupId
from app.services.saga.saga_manager import SagaOrchestratorManagerSingleton, get_saga_orchestrator_manager


async def run_saga_orchestrator() -> None:
    """Run the saga orchestrator"""
    # Get settings
    settings = get_settings()

    # Create and set database manager
    db_manager = DatabaseManager(settings)
    await db_manager.connect_to_database()
    SagaOrchestratorManagerSingleton.set_database_manager(db_manager)

    # Get saga manager
    manager = await get_saga_orchestrator_manager()

    # Get orchestrator (this will initialize and start it)
    _ = await manager.get_orchestrator()

    logger = logging.getLogger(__name__)
    logger.info("Saga orchestrator started and running")

    try:
        # Keep running
        while True:
            await asyncio.sleep(60)

            # Log status periodically
            logger.info("Saga orchestrator is running...")

    except asyncio.CancelledError:
        logger.info("Saga orchestrator cancelled")
    finally:
        await manager.shutdown()
        await db_manager.close_database_connection()


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
