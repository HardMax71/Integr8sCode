"""Run PodMonitor as a standalone worker service"""

import asyncio
import logging

from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.services.pod_monitor.monitor import run_pod_monitor
from app.settings import get_settings


def main() -> None:
    """Main entry point for pod monitor worker"""
    settings = get_settings()

    # Setup logging
    logger = setup_logger(settings.LOG_LEVEL)

    # Configure root logger for worker
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting PodMonitor worker...")

    # Initialize tracing
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.POD_MONITOR,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for PodMonitor Service")

    asyncio.run(run_pod_monitor())


if __name__ == "__main__":
    main()
