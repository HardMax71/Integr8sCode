import asyncio
import logging
import signal

from app.core.container import create_coordinator_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.services.coordinator.coordinator import ExecutionCoordinator
from app.settings import Settings, get_settings


async def run_coordinator(settings: Settings | None = None) -> None:
    """Run the execution coordinator service."""
    if settings is None:
        settings = get_settings()

    container = create_coordinator_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting ExecutionCoordinator with DI container...")

    # Services are already started by the DI container providers
    coordinator = await container.get(ExecutionCoordinator)

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("ExecutionCoordinator started and running")

    try:
        # Wait for shutdown signal or service to stop
        while coordinator.is_running and not shutdown_event.is_set():
            await asyncio.sleep(60)
            status = await coordinator.get_status()
            logger.info(f"Coordinator status: {status}")
    finally:
        # Container cleanup stops everything
        logger.info("Initiating graceful shutdown...")
        await container.close()


def main() -> None:
    """Main entry point for coordinator worker"""
    settings = get_settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting ExecutionCoordinator worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.EXECUTION_COORDINATOR,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for ExecutionCoordinator")

    asyncio.run(run_coordinator(settings))


if __name__ == "__main__":
    main()
