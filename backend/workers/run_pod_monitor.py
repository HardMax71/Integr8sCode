import asyncio
import logging
import signal

from app.core.container import create_pod_monitor_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.pod_monitor.monitor import MonitorState, PodMonitor
from app.settings import Settings
from beanie import init_beanie

RECONCILIATION_LOG_INTERVAL: int = 60


async def run_pod_monitor(settings: Settings) -> None:
    """Run the pod monitor service."""

    container = create_pod_monitor_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting PodMonitor with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Services are already started by the DI container providers
    monitor = await container.get(PodMonitor)

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("PodMonitor started and running")

    try:
        # Wait for shutdown signal or service to stop
        while monitor.state == MonitorState.RUNNING and not shutdown_event.is_set():
            await asyncio.sleep(RECONCILIATION_LOG_INTERVAL)
            status = await monitor.get_status()
            logger.info(f"Pod monitor status: {status}")
    finally:
        # Container cleanup stops everything
        logger.info("Initiating graceful shutdown...")
        await container.close()


def main() -> None:
    """Main entry point for pod monitor worker"""
    settings = Settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting PodMonitor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.POD_MONITOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for PodMonitor Service")

    asyncio.run(run_pod_monitor(settings))


if __name__ == "__main__":
    main()
