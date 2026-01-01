import asyncio
import logging
import signal
from contextlib import AsyncExitStack

from app.core.container import create_pod_monitor_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.pod_monitor.monitor import MonitorState, PodMonitor
from app.settings import Settings, get_settings
from beanie import init_beanie

RECONCILIATION_LOG_INTERVAL: int = 60


async def run_pod_monitor(settings: Settings | None = None) -> None:
    """Run the pod monitor service."""
    if settings is None:
        settings = get_settings()

    container = create_pod_monitor_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting PodMonitor with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    producer = await container.get(UnifiedProducer)
    monitor = await container.get(PodMonitor)

    loop = asyncio.get_running_loop()

    async def shutdown() -> None:
        logger.info("Initiating graceful shutdown...")
        await monitor.stop()
        await producer.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(producer)
        await stack.enter_async_context(monitor)
        stack.push_async_callback(container.close)

        while monitor.state == MonitorState.RUNNING:
            await asyncio.sleep(RECONCILIATION_LOG_INTERVAL)
            status = await monitor.get_status()
            logger.info(f"Pod monitor status: {status}")


def main() -> None:
    """Main entry point for pod monitor worker"""
    settings = get_settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting PodMonitor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.POD_MONITOR,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for PodMonitor Service")

    asyncio.run(run_pod_monitor(settings))


if __name__ == "__main__":
    main()
