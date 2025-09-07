"""Run ExecutionCoordinator as a standalone worker service"""

import asyncio
import logging

from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.services.coordinator.coordinator import run_coordinator
from app.settings import get_settings


def main() -> None:
    """Main entry point for coordinator worker"""
    # Setup logging
    setup_logger()

    # Configure root logger for worker
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting ExecutionCoordinator worker...")

    # Initialize tracing
    settings = get_settings()
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.EXECUTION_COORDINATOR,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE
        )
        logger.info("Tracing initialized for ExecutionCoordinator")

    try:
        # Run coordinator
        asyncio.run(run_coordinator())
    except KeyboardInterrupt:
        logger.info("Coordinator worker interrupted by user")
    except Exception as e:
        logger.error(f"Coordinator worker failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
