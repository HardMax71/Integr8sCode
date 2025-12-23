import asyncio
import logging

from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.services.result_processor.processor import run_result_processor
from app.settings import get_settings


def main() -> None:
    """Main entry point for result processor worker"""
    # Setup logging
    setup_logger()

    # Configure root logger for worker
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger = logging.getLogger(__name__)
    logger.info("Starting ResultProcessor worker...")

    # Initialize tracing
    settings = get_settings()
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.RESULT_PROCESSOR,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for ResultProcessor Service")

    asyncio.run(run_result_processor())


if __name__ == "__main__":
    main()
